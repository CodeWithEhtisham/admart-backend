"""One-time download of the free local models agents use (no GPU needed).

    python manage.py download_agent_models

- Kokoro voice (int8 ONNX, ~90 MB + 28 MB voices) into AGENTS_KOKORO_DIR
- faster-whisper caption-timing model (AGENTS_WHISPER_MODEL) into AGENTS_WHISPER_DIR
Safe to re-run: files already present are skipped.
"""

from pathlib import Path

import requests
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from agents.providers import KOKORO_MODEL, KOKORO_VOICES

KOKORO_RELEASE = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0"


class Command(BaseCommand):
    help = "Download the free local voice (Kokoro) and caption-timing (faster-whisper) models."

    def handle(self, *args, **options):
        folder = Path(settings.AGENTS_KOKORO_DIR)
        folder.mkdir(parents=True, exist_ok=True)
        for name in (KOKORO_MODEL, KOKORO_VOICES):
            self._download(f"{KOKORO_RELEASE}/{name}", folder / name)

        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise CommandError("faster-whisper is not installed: pip install kokoro-onnx faster-whisper") from exc
        Path(settings.AGENTS_WHISPER_DIR).mkdir(parents=True, exist_ok=True)
        self.stdout.write(f"Fetching whisper model {settings.AGENTS_WHISPER_MODEL}…")
        WhisperModel(settings.AGENTS_WHISPER_MODEL, device="cpu", compute_type="int8",
                     download_root=settings.AGENTS_WHISPER_DIR)
        self.stdout.write(self.style.SUCCESS("Agent models ready."))

    def _download(self, url: str, target: Path) -> None:
        if target.exists() and target.stat().st_size > 0:
            self.stdout.write(f"{target.name}: already present")
            return
        self.stdout.write(f"Downloading {target.name}…")
        partial = target.with_suffix(target.suffix + ".part")
        with requests.get(url, stream=True, timeout=60) as response:
            response.raise_for_status()
            with partial.open("wb") as fh:
                for chunk in response.iter_content(chunk_size=1 << 20):
                    fh.write(chunk)
        partial.rename(target)  # only a complete file ever has the final name
