"""Local credential storage — never commit token files."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from discovery.config import publishing_credentials_dir


def credentials_path(account_id: int) -> Path:
    return publishing_credentials_dir() / f"account_{account_id:06d}.json"


def save_credentials(account_id: int, payload: dict[str, Any]) -> str:
    path = credentials_path(account_id)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return str(path)


def load_credentials(account_id: int) -> dict[str, Any]:
    path = credentials_path(account_id)
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def delete_credentials(account_id: int) -> None:
    path = credentials_path(account_id)
    if path.is_file():
        path.unlink()
