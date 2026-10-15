"""Resumable chunked upload of long videos into the Library (up to LIBRARY_LARGE_VIDEO_BYTES).

POST   /api/projects/:pid/library/uploads/large                → start: {id, chunkBytes, received}
GET    /api/projects/:pid/library/uploads/large/:id            → {received} (where to continue)
PUT    /api/projects/:pid/library/uploads/large/:id            → one chunk, raw bytes + Content-Range
POST   /api/projects/:pid/library/uploads/large/:id/finish     → checks it is a video, adds it to the Library

Chunks must arrive in order; a repeated or out-of-order chunk gets 409 with the offset to continue
from, so a browser can resume after a dropped connection. Sessions live in PRIVATE_MEDIA_ROOT/uploads
(never web-served) and are owned by one user and project; stale ones are removed after a day.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import time
import uuid
from pathlib import Path

from django.conf import settings
from django.core.files.storage import default_storage
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from content.models import LibraryAsset
from content.storage_utils import absolute_media_url
from projects.models import Project

VIDEO_EXT = {"video/mp4": ".mp4", "video/quicktime": ".mov", "video/webm": ".webm", "video/x-m4v": ".m4v"}
SESSION_ID = re.compile(r"^[0-9a-f]{32}$")
RANGE = re.compile(r"^bytes (\d+)-(\d+)/(\d+)$")
STALE_SECONDS = 24 * 3600
MAX_OPEN_PER_USER = 3  # unfinished uploads; stops one account filling the disk


def _root() -> Path:
    return Path(settings.PRIVATE_MEDIA_ROOT) / "uploads"


def _bad(message: str, http=status.HTTP_400_BAD_REQUEST, **extra) -> Response:
    return Response({"message": message, **extra}, status=http)


def _clean_stale() -> None:
    root = _root()
    if not root.exists():
        return
    for folder in root.iterdir():
        try:
            if time.time() - folder.stat().st_mtime > STALE_SECONDS:
                shutil.rmtree(folder, ignore_errors=True)
        except OSError:
            continue


class _Session:
    def __init__(self, request, project_id, upload_id):
        self.project = get_object_or_404(Project, id=project_id, owner=request.user)
        if not SESSION_ID.match(upload_id or ""):
            raise FileNotFoundError
        self.folder = _root() / upload_id
        meta = self.folder / "meta.json"
        if not meta.exists():
            raise FileNotFoundError
        self.meta = json.loads(meta.read_text())
        if self.meta["user"] != str(request.user.id) or self.meta["project"] != str(self.project.id):
            raise FileNotFoundError
        self.data = self.folder / "data.part"

    @property
    def received(self) -> int:
        return self.data.stat().st_size if self.data.exists() else 0


def _probe(path: Path) -> dict | None:
    """Duration and size of a real video file, or None."""
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_type,width,height", "-of", "json",
             str(path)], capture_output=True, text=True, timeout=120,
        )
        data = json.loads(out.stdout or "{}")
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None
    video = next((s for s in data.get("streams") or [] if s.get("codec_type") == "video"), None)
    duration = float((data.get("format") or {}).get("duration") or 0)
    if not video or duration <= 0:
        return None
    return {"duration": duration, "width": int(video.get("width") or 0), "height": int(video.get("height") or 0)}


class LargeUploadStartView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, project_id):
        project = get_object_or_404(Project, id=project_id, owner=request.user)
        content_type = str(request.data.get("contentType") or "").split(";")[0].strip().lower()
        if content_type not in VIDEO_EXT:
            return _bad("Only mp4, mov or webm videos can be uploaded this way.")
        try:
            size = int(request.data.get("size"))
        except (TypeError, ValueError):
            return _bad("Tell us the file size.")
        if size <= 0:
            return _bad("This file is empty.")
        if size > settings.LIBRARY_LARGE_VIDEO_BYTES:
            limit = settings.LIBRARY_LARGE_VIDEO_BYTES // 1024**3
            return _bad(f"Videos can be up to {limit} GB.", status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)
        _clean_stale()
        mine = 0
        for meta in _root().glob("*/meta.json") if _root().exists() else []:
            try:
                mine += json.loads(meta.read_text()).get("user") == str(request.user.id)
            except (OSError, ValueError):
                continue
        if mine >= MAX_OPEN_PER_USER:
            return _bad("Finish or wait for your other uploads first.", status.HTTP_429_TOO_MANY_REQUESTS)
        upload_id = uuid.uuid4().hex
        folder = _root() / upload_id
        folder.mkdir(parents=True)
        raw_name = Path(str(request.data.get("fileName") or "")).stem
        title = "".join(c for c in raw_name if c.isprintable() and c not in "/\\")[:255] or "Uploaded video"
        (folder / "meta.json").write_text(json.dumps({
            "user": str(request.user.id), "project": str(project.id), "size": size,
            "contentType": content_type, "title": title,
        }))
        return Response({"id": upload_id, "chunkBytes": settings.LIBRARY_UPLOAD_CHUNK_BYTES, "received": 0},
                        status=status.HTTP_201_CREATED)


class LargeUploadChunkView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, project_id, upload_id):
        try:
            session = _Session(request, project_id, upload_id)
        except FileNotFoundError:
            return _bad("Upload not found.", status.HTTP_404_NOT_FOUND)
        return Response({"received": session.received, "size": session.meta["size"]})

    def put(self, request, project_id, upload_id):
        try:
            session = _Session(request, project_id, upload_id)
        except FileNotFoundError:
            return _bad("Upload not found.", status.HTTP_404_NOT_FOUND)
        match = RANGE.match(request.headers.get("Content-Range", ""))
        if not match:
            return _bad("Send each chunk with a Content-Range header.")
        start, end, total = map(int, match.groups())
        if total != session.meta["size"] or end < start or end >= total:
            return _bad("The chunk doesn't fit this upload.")
        if end - start + 1 > settings.LIBRARY_UPLOAD_CHUNK_BYTES:
            return _bad("Chunk too large.", status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)
        received = session.received
        if start != received:
            return _bad("Continue from where the upload stopped.", status.HTTP_409_CONFLICT, received=received)
        body = request.body
        if len(body) != end - start + 1:
            return _bad("The chunk arrived incomplete.", received=received)
        with open(session.data, "ab") as handle:
            handle.write(body)
        return Response({"received": received + len(body)})


class LargeUploadFinishView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, project_id, upload_id):
        try:
            session = _Session(request, project_id, upload_id)
        except FileNotFoundError:
            return _bad("Upload not found.", status.HTTP_404_NOT_FOUND)
        if session.received != session.meta["size"]:
            return _bad("The upload isn't complete yet.", received=session.received)
        info = _probe(session.data)
        if info is None:  # never trust the declared type: it must really be a video
            shutil.rmtree(session.folder, ignore_errors=True)
            return _bad("This file isn't a video we can read. Try exporting it as MP4.")
        rel = f"projects/{session.project.id}/library/{uuid.uuid4().hex}{VIDEO_EXT[session.meta['contentType']]}"
        target = Path(default_storage.path(rel))
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(session.data), target)
        shutil.rmtree(session.folder, ignore_errors=True)
        url = absolute_media_url(rel, request=request)
        asset = LibraryAsset.objects.create(
            project=session.project, user=request.user, media_type="video", title=session.meta["title"],
            status="ready", thumbnail_url=url, source_url=url, capability="upload", model="upload",
            duration_seconds=round(info["duration"]), width=info["width"], height=info["height"],
        )
        from content.serializers import LibraryAssetSerializer

        data = LibraryAssetSerializer(asset).data
        data["sourceUrl"] = data["thumbnailUrl"] = url
        return Response(data, status=status.HTTP_201_CREATED)
