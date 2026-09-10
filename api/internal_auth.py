"""Minimal protection for private internal endpoints."""

from __future__ import annotations

from fastapi import Header, HTTPException

from discovery.config import internal_api_key  # noqa: E402 — scripts/ on path via api package


def require_internal_key(x_internal_key: str | None = Header(default=None)) -> None:
    expected = internal_api_key()
    if not expected:
        return
    if x_internal_key != expected:
        raise HTTPException(status_code=401, detail="Invalid or missing X-Internal-Key")
