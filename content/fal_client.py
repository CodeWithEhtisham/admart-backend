"""Thin fal.ai queue client over HTTPS (uses existing `requests`)."""

from __future__ import annotations

import logging
from dataclasses import dataclass

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

QUEUE_BASE = "https://queue.fal.run"
REQUEST_TIMEOUT = 60


class FalError(Exception):
    """Raised when fal submit/status/result fails."""

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class FalSubmission:
    request_id: str
    status_url: str
    response_url: str


def _auth_headers(*, json_body: bool = False) -> dict:
    key = settings.FAL_KEY
    if not key:
        raise FalError("FAL_KEY is not configured", status_code=503)
    headers = {"Authorization": f"Key {key}"}
    if json_body:
        headers["Content-Type"] = "application/json"
    return headers


def _queue_base_for_model(model: str) -> str:
    """Best-effort fallback when status_url was not stored.

    fal apps with a subpath (e.g. fal-ai/flux/dev) expose queue ops on the parent
    app (fal-ai/flux). Prefer submit's status_url / response_url whenever available.
    """
    parts = model.strip("/").split("/")
    if len(parts) >= 3:
        # fal-ai/flux/dev → fal-ai/flux ; fal-ai/nano-banana-2/edit → fal-ai/nano-banana-2
        return f"{QUEUE_BASE}/{'/'.join(parts[:-1])}"
    return f"{QUEUE_BASE}/{model}"


def submit(model: str, arguments: dict) -> FalSubmission:
    """Submit a job; return fal request id + canonical poll URLs."""
    url = f"{QUEUE_BASE}/{model}"
    resp = requests.post(
        url, headers=_auth_headers(json_body=True), json=arguments, timeout=REQUEST_TIMEOUT
    )
    if resp.status_code >= 400:
        logger.warning(
            "fal submit failed model=%s status=%s body=%s",
            model,
            resp.status_code,
            resp.text[:500],
        )
        raise FalError("Provider error", status_code=502)
    data = resp.json()
    request_id = data.get("request_id") or data.get("requestId")
    if not request_id:
        raise FalError("Provider error", status_code=502)

    base = _queue_base_for_model(model)
    status_url = data.get("status_url") or f"{base}/requests/{request_id}/status"
    response_url = data.get("response_url") or f"{base}/requests/{request_id}"
    return FalSubmission(
        request_id=request_id,
        status_url=status_url,
        response_url=response_url,
    )


def status(*, status_url: str | None = None, model: str = "", request_id: str = "") -> dict:
    """Return fal status payload (includes status string)."""
    url = status_url or f"{_queue_base_for_model(model)}/requests/{request_id}/status"
    resp = requests.get(url, headers=_auth_headers(), timeout=REQUEST_TIMEOUT)
    if resp.status_code >= 400:
        logger.warning("fal status failed url=%s status=%s body=%s", url, resp.status_code, resp.text[:200])
        raise FalError("Provider error", status_code=502)
    return resp.json()


def _error_message(resp: requests.Response, fallback: str = "Provider error") -> str:
    """Extract a safe, user-facing message from a fal error body."""
    try:
        data = resp.json()
    except Exception:
        return fallback
    detail = data.get("detail")
    if isinstance(detail, list) and detail:
        first = detail[0]
        if isinstance(first, dict) and first.get("msg"):
            return str(first["msg"])
        return str(first)
    if isinstance(detail, str) and detail:
        return detail
    if data.get("error"):
        return str(data["error"])
    return fallback


def result(*, response_url: str | None = None, model: str = "", request_id: str = "") -> dict:
    """Return completed fal result payload."""
    url = response_url or f"{_queue_base_for_model(model)}/requests/{request_id}"
    resp = requests.get(url, headers=_auth_headers(), timeout=REQUEST_TIMEOUT)
    if resp.status_code >= 400:
        msg = _error_message(resp)
        logger.warning(
            "fal result failed url=%s status=%s body=%s", url, resp.status_code, resp.text[:300]
        )
        raise FalError(msg, status_code=resp.status_code)
    return resp.json()
