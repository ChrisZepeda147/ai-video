"""Resolve ffmpeg/ffprobe/yt-dlp for API and Cursor-bridge subprocesses.

Child processes spawned by uvicorn threads often inherit a reduced PATH on Windows.
This module merges User + Machine PATH, honors FFMPEG_DIR / FFMPEG_PATH, and exposes
early dependency checks so jobs fail fast with FFMPEG_NOT_FOUND instead of retrying
every speech candidate.
"""

from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_APPLIED = False
_FFMPEG_DIR: Path | None = None


@dataclass(frozen=True)
class ToolStatus:
    name: str
    found: bool
    path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "found": self.found, "path": self.path}


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _load_dotenv() -> None:
    try:
        from discovery.config import load_env

        load_env()
    except Exception:
        env_path = Path(__file__).resolve().parent / ".env"
        if not env_path.is_file():
            return
        for raw in env_path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value


def _windows_path_from_registry(scope: str) -> str:
    if sys.platform != "win32":
        return ""
    try:
        import winreg

        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER if scope == "user" else winreg.HKEY_LOCAL_MACHINE, "Environment")
        value, _ = winreg.QueryValueEx(key, "Path")
        winreg.CloseKey(key)
        return str(value or "")
    except OSError:
        return ""


def _merge_path_entries(*parts: str) -> str:
    seen: set[str] = set()
    ordered: list[str] = []
    for part in parts:
        for entry in part.split(os.pathsep):
            entry = entry.strip().strip('"')
            if not entry:
                continue
            key = entry.lower()
            if key in seen:
                continue
            seen.add(key)
            ordered.append(entry)
    return os.pathsep.join(ordered)


def _configured_ffmpeg_dir() -> Path | None:
    for key in ("FFMPEG_DIR", "FFMPEG_PATH", "FFMPEG_HOME"):
        raw = os.environ.get(key, "").strip().strip('"')
        if not raw:
            continue
        path = Path(raw)
        if path.is_file():
            path = path.parent
        if path.is_dir():
            return path
    return None


def _candidate_ffmpeg_dirs() -> list[Path]:
    dirs: list[Path] = []
    configured = _configured_ffmpeg_dir()
    if configured:
        dirs.append(configured)
    home = Path.home()
    for rel in (
        "ffmpeg/bin",
        "AppData/Local/ffmpeg/bin",
        "scoop/apps/ffmpeg/current/bin",
        "scoop/shims",
    ):
        dirs.append(home / rel)
    program_files = Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
    for fixed in (
        program_files
        / "Streamlabs OBS"
        / "resources"
        / "app.asar.unpacked"
        / "node_modules"
        / "obs-studio-node",
        program_files / "SteelSeries" / "GG" / "apps" / "moments",
        Path(r"C:\ffmpeg\bin"),
        Path(r"C:\Program Files\ffmpeg\bin"),
        Path(r"C:\Program Files\Gyan\FFmpeg\bin"),
        program_files / "ffmpeg" / "bin",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Links",
        Path(os.environ.get("ProgramData", r"C:\ProgramData")) / "chocolatey" / "bin",
    ):
        if str(fixed).strip():
            dirs.append(fixed)
    return dirs


def _discover_ffmpeg_dir() -> Path | None:
    configured = _configured_ffmpeg_dir()
    if configured and (configured / "ffmpeg.exe").is_file():
        return configured
    for directory in _candidate_ffmpeg_dirs():
        if (directory / "ffmpeg.exe").is_file() and (directory / "ffprobe.exe").is_file():
            return directory
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    if ffmpeg and ffprobe:
        return Path(ffmpeg).parent
    return None


def apply_to_os_environ() -> dict[str, str]:
    """Merge PATH and cache ffmpeg directory. Returns os.environ copy."""
    global _APPLIED, _FFMPEG_DIR
    _load_dotenv()

    user_path = _windows_path_from_registry("user") if sys.platform == "win32" else ""
    machine_path = _windows_path_from_registry("machine") if sys.platform == "win32" else ""
    merged = _merge_path_entries(user_path, machine_path, os.environ.get("PATH", ""))

    ffmpeg_dir = _discover_ffmpeg_dir()
    if ffmpeg_dir:
        merged = _merge_path_entries(str(ffmpeg_dir), merged)
        _FFMPEG_DIR = ffmpeg_dir

    os.environ["PATH"] = merged
    _APPLIED = True
    return os.environ.copy()


def subprocess_env() -> dict[str, str]:
    return apply_to_os_environ()


def _imageio_ffmpeg() -> str | None:
    try:
        import imageio_ffmpeg

        path = imageio_ffmpeg.get_ffmpeg_exe()
        return path if Path(path).is_file() else None
    except Exception:
        return None


def resolve_tool(name: str) -> str | None:
    apply_to_os_environ()
    if name == "ffmpeg":
        imageio = _imageio_ffmpeg()
        if imageio:
            return imageio
    found = shutil.which(name)
    if found:
        return found
    if _FFMPEG_DIR and (_FFMPEG_DIR / f"{name}.exe").is_file():
        return str(_FFMPEG_DIR / f"{name}.exe")
    return None


def ffmpeg_location() -> str | None:
    apply_to_os_environ()
    if _FFMPEG_DIR and (_FFMPEG_DIR / "ffmpeg.exe").is_file():
        return str(_FFMPEG_DIR)
    ffmpeg = shutil.which("ffmpeg")
    return str(Path(ffmpeg).parent) if ffmpeg else None


def ytdlp_ffmpeg_opts() -> dict[str, str]:
    location = ffmpeg_location()
    return {"ffmpeg_location": location} if location else {}


def check_toolchain() -> dict[str, Any]:
    apply_to_os_environ()
    ffmpeg = resolve_tool("ffmpeg")
    ffprobe = resolve_tool("ffprobe")
    ytdlp = resolve_tool("yt-dlp")
    if not ytdlp:
        try:
            import yt_dlp  # noqa: F401

            ytdlp = sys.executable
        except ImportError:
            ytdlp = None
    ok = bool(ffmpeg and ffprobe and ytdlp)
    return {
        "ok": ok,
        "ffmpeg": ToolStatus("ffmpeg", bool(ffmpeg), ffmpeg).to_dict(),
        "ffprobe": ToolStatus("ffprobe", bool(ffprobe), ffprobe).to_dict(),
        "yt-dlp": ToolStatus("yt-dlp", bool(ytdlp), ytdlp).to_dict(),
        "ffmpeg_location": ffmpeg_location(),
        "ffmpeg_encoding": ffmpeg,
        "ffprobe_source": ffprobe,
    }


def format_toolchain_report(check: dict[str, Any] | None = None) -> str:
    check = check or check_toolchain()
    lines = ["Toolchain:"]
    for key in ("ffmpeg", "ffprobe", "yt-dlp"):
        item = check.get(key) or {}
        status = item.get("path") or "NOT FOUND"
        lines.append(f"  {key}: {status}")
    loc = check.get("ffmpeg_location")
    if loc:
        lines.append(f"  yt-dlp ffmpeg_location: {loc}")
    return "\n".join(lines)


def classify_download_error(error: str | BaseException | None) -> str:
    text = str(error or "").lower()
    if not text:
        return "DOWNLOAD_FAILED"
    if "ffprobe and ffmpeg not found" in text or "ffmpeg not found" in text:
        return "FFMPEG_NOT_FOUND"
    if "postprocessing" in text and "ffmpeg" in text:
        return "POSTPROCESS_FAILED"
    if "video unavailable" in text or "private video" in text or "age-restricted" in text:
        return "SOURCE_UNAVAILABLE"
    if "sign in" in text or "confirm your age" in text:
        return "SOURCE_UNAVAILABLE"
    return "DOWNLOAD_FAILED"
