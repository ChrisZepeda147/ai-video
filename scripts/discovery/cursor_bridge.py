"""Invoke Cursor Agent CLI from the ai-video project (non-interactive)."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from discovery.config import cursor_api_key, project_root

try:
    from toolchain_env import subprocess_env
except ImportError:
    subprocess_env = None  # type: ignore[assignment]


@dataclass
class AgentRunResult:
    ok: bool
    exit_code: int
    result_text: str = ""
    session_id: str | None = None
    request_id: str | None = None
    stdout: str = ""
    stderr: str = ""
    messages: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None
    dry_run: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "exit_code": self.exit_code,
            "result_text": self.result_text,
            "session_id": self.session_id,
            "request_id": self.request_id,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "messages": self.messages,
            "error": self.error,
            "dry_run": self.dry_run,
        }


def _candidate_agent_dirs() -> list[Path]:
    dirs: list[Path] = []
    local = os.environ.get("LOCALAPPDATA", "").strip()
    if local:
        dirs.append(Path(local) / "cursor-agent")
    home = Path.home()
    dirs.extend(
        [
            home / ".local" / "bin",
            home / "AppData" / "Local" / "cursor-agent",
        ]
    )
    return dirs


def find_agent_binary() -> str | None:
    if subprocess_env:
        subprocess_env()
    for name in ("agent", "cursor-agent"):
        path = shutil.which(name)
        if path:
            return path
    for directory in _candidate_agent_dirs():
        for name in ("agent.cmd", "agent.CMD", "agent.ps1", "agent.exe", "agent"):
            candidate = directory / name
            if candidate.is_file():
                return str(candidate)
    return None


def agent_available() -> bool:
    return find_agent_binary() is not None or _dry_run_enabled()


def _dry_run_enabled() -> bool:
    return os.environ.get("CURSOR_BRIDGE_DRY_RUN", "").strip().lower() in {"1", "true", "yes"}


def create_chat(*, workspace: Path | None = None) -> str | None:
    binary = find_agent_binary()
    if not binary:
        return None
    root = workspace or project_root()
    env = subprocess_env() if subprocess_env else os.environ.copy()
    key = cursor_api_key()
    if key:
        env["CURSOR_API_KEY"] = key
    result = subprocess.run(
        [binary, "create-chat"],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        timeout=60,
    )
    if result.returncode != 0:
        return None
    chat_id = (result.stdout or "").strip().splitlines()[-1].strip()
    return chat_id or None


def _parse_stream_json_lines(lines: str) -> tuple[list[dict[str, Any]], str, str | None, str | None]:
    messages: list[dict[str, Any]] = []
    result_text = ""
    session_id: str | None = None
    request_id: str | None = None
    for raw in lines.splitlines():
        line = raw.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        messages.append(event)
        session_id = event.get("session_id") or session_id
        if event.get("type") == "result":
            request_id = event.get("request_id") or request_id
            if event.get("subtype") == "success":
                result_text = str(event.get("result") or result_text)
            elif event.get("is_error"):
                result_text = str(event.get("result") or event.get("message") or result_text)
    return messages, result_text, session_id, request_id


def default_agent_model() -> str | None:
    return os.environ.get("CURSOR_AGENT_MODEL", "").strip() or None


def run_agent(
    prompt: str,
    *,
    job_id: str | None = None,
    video_id: int | None = None,
    session_id: str | None = None,
    workspace: Path | None = None,
    force: bool = True,
    trust: bool = True,
    timeout_sec: int = 3600,
    model: str | None = None,
) -> AgentRunResult:
    """Run Cursor Agent headlessly with a natural-language prompt."""
    root = workspace or project_root()
    if _dry_run_enabled():
        return AgentRunResult(
            ok=True,
            exit_code=0,
            result_text=f"[DRY RUN] Received prompt ({len(prompt)} chars). job={job_id} video={video_id}",
            session_id=session_id or "dry-run-session",
            stdout="",
            stderr="",
            dry_run=True,
        )

    binary = find_agent_binary()
    if not binary:
        return AgentRunResult(
            ok=False,
            exit_code=127,
            error=(
                "Cursor Agent CLI not found. Install with: "
                "irm 'https://cursor.com/install?win32=true' | iex "
                "Or set CURSOR_BRIDGE_DRY_RUN=1 for offline testing."
            ),
        )

    cmd = [
        binary,
        "-p",
        "--output-format",
        "stream-json",
        "--workspace",
        str(root),
    ]
    resolved_model = (model or "").strip() or default_agent_model()
    if resolved_model:
        cmd.extend(["--model", resolved_model])
    if force:
        cmd.append("--force")
    if trust:
        cmd.append("--trust")
    if session_id:
        cmd.extend(["--resume", session_id])
    cmd.append(prompt)

    env = subprocess_env() if subprocess_env else os.environ.copy()
    key = cursor_api_key()
    if key:
        env["CURSOR_API_KEY"] = key

    try:
        completed = subprocess.run(
            cmd,
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            timeout=timeout_sec,
        )
    except subprocess.TimeoutExpired as exc:
        return AgentRunResult(
            ok=False,
            exit_code=124,
            stdout=exc.stdout or "",
            stderr=exc.stderr or "",
            error=f"Cursor Agent timed out after {timeout_sec}s",
        )
    except OSError as exc:
        return AgentRunResult(
            ok=False,
            exit_code=1,
            error=str(exc),
        )

    stdout = completed.stdout or ""
    stderr = completed.stderr or ""
    messages, result_text, parsed_session, request_id = _parse_stream_json_lines(stdout)
    if not result_text and stdout and not messages:
        result_text = stdout.strip()

    ok = completed.returncode == 0
    error = None if ok else (stderr.strip() or result_text or f"agent exited {completed.returncode}")
    return AgentRunResult(
        ok=ok,
        exit_code=completed.returncode,
        result_text=result_text,
        session_id=parsed_session or session_id,
        request_id=request_id,
        stdout=stdout,
        stderr=stderr,
        messages=messages,
        error=error,
    )
