#!/usr/bin/env python3
"""
Upload videos and photos to TikTok through the official Content Posting API.

Setup (you do this once in the TikTok developer portal):
  1. Create an app at https://developers.tiktok.com/
  2. Enable Content Posting API and request video.publish + user.info.basic
  3. Register redirect URI http://127.0.0.1:8787/callback (desktop / loopback)
  4. Put TIKTOK_CLIENT_KEY and TIKTOK_CLIENT_SECRET in scripts/.env
  5. Run: python scripts/tiktok_upload.py auth

Photo posts only accept public image URLs from a URL prefix you verify in that
same portal. Local stills cannot be uploaded as photos. Pass --image-url.

Photo music is always auto-picked (auto_add_music=true). Change the sound later
in the TikTok app. There is no music-id argument.

Examples:
  python scripts/tiktok_upload.py auth
  python scripts/tiktok_upload.py video downloads/imessage/dont-go-inside/part01_final.mp4 --story-file downloads/imessage/dont-go-inside/story.json --hashtags "#fyp #storytime"
  python scripts/tiktok_upload.py photo --image-url https://your-verified-domain/still.png --title "midnight driveway" --hashtags "#fyp #luxury"
  python scripts/tiktok_upload.py status --publish-id "v_pub_file~v2-1.123"
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import secrets
import subprocess
import sys
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import Request, urlopen

API_BASE = "https://open.tiktokapis.com"
AUTHORIZE_URL = "https://www.tiktok.com/v2/auth/authorize/"
DEFAULT_REDIRECT = "http://127.0.0.1:8787/callback"
DEFAULT_SCOPES = "user.info.basic,video.publish"
DEFAULT_THUMB_DIR = Path("prompts/dark-luxury-still")
PHOTO_EXTS = {".png", ".jpg", ".jpeg", ".webp"}
THUMB_EXCLUDE_NAMES = {"reference.png"}
PRIVACY_CHOICES = (
    "SELF_ONLY",
    "MUTUAL_FOLLOW_FRIENDS",
    "FOLLOWER_OF_CREATOR",
    "PUBLIC_TO_EVERYONE",
)
VIDEO_CAPTION_LIMIT = 2200
PHOTO_TITLE_LIMIT = 90
PHOTO_DESCRIPTION_LIMIT = 4000
PHOTO_MAX_IMAGES = 35
CHUNK_SIZE = 10 * 1024 * 1024
STATUS_POLL_SEC = 3.0
STATUS_TIMEOUT_SEC = 600.0
COVER_FPS = 25.0
COVER_FRAME_MS = 0


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _kino_exe() -> Path:
    return _project_root() / "tools" / "kinocut" / ".venv" / "Scripts" / "kino.exe"


def _env_path() -> Path:
    return Path(__file__).resolve().parent / ".env"


def _token_path() -> Path:
    return Path(__file__).resolve().parent / ".tiktok_tokens.json"


def _load_env() -> None:
    env_path = _env_path()
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


def _utf16_len(text: str) -> int:
    return len(text.encode("utf-16-le")) // 2


def _clip_utf16(text: str, limit: int) -> str:
    if _utf16_len(text) <= limit:
        return text
    clipped = []
    used = 0
    for char in text:
        size = _utf16_len(char)
        if used + size > limit:
            break
        clipped.append(char)
        used += size
    return "".join(clipped)


def _run(cmd: list[str], *, quiet: bool = False) -> None:
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(f"Command failed ({result.returncode}): {' '.join(cmd)}\n{detail}")
    if not quiet and result.stdout.strip():
        print(result.stdout.rstrip())


def _client_credentials() -> tuple[str, str, str]:
    key = os.environ.get("TIKTOK_CLIENT_KEY", "").strip()
    secret = os.environ.get("TIKTOK_CLIENT_SECRET", "").strip()
    redirect = os.environ.get("TIKTOK_REDIRECT_URI", DEFAULT_REDIRECT).strip() or DEFAULT_REDIRECT
    if not key or not secret:
        raise SystemExit(
            "Missing TIKTOK_CLIENT_KEY or TIKTOK_CLIENT_SECRET.\n"
            "Add them to scripts/.env, then run: python scripts/tiktok_upload.py auth"
        )
    return key, secret, redirect


def _pkce_pair() -> tuple[str, str]:
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~"
    verifier = "".join(secrets.choice(alphabet) for _ in range(64))
    challenge = hashlib.sha256(verifier.encode("utf-8")).hexdigest()
    return verifier, challenge


def _http_json(
    method: str,
    url: str,
    *,
    token: str | None = None,
    body: dict[str, Any] | None = None,
    form: dict[str, str] | None = None,
) -> dict[str, Any]:
    headers: dict[str, str] = {}
    data: bytes | None = None
    if form is not None:
        data = urlencode(form).encode("utf-8")
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    elif body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json; charset=UTF-8"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(url, data=data, headers=headers, method=method)
    try:
        with urlopen(request, timeout=120) as response:
            raw = response.read().decode("utf-8")
    except HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            parsed = {}
        error = parsed.get("error")
        if isinstance(error, dict):
            message = error.get("message") or error.get("code") or raw or str(exc)
        else:
            message = parsed.get("error_description") or error or raw or str(exc)
        raise RuntimeError(f"TikTok HTTP {exc.code}: {message}") from exc
    except URLError as exc:
        raise RuntimeError(f"TikTok request failed: {exc.reason}") from exc
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"TikTok returned non-JSON: {raw[:400]}") from exc


def _api_data(payload: dict[str, Any]) -> dict[str, Any]:
    error = payload.get("error")
    if isinstance(error, dict):
        code = error.get("code") or ""
        if code and code != "ok":
            raise RuntimeError(f"TikTok API error ({code}): {error.get('message') or code}")
    elif isinstance(error, str) and error:
        raise RuntimeError(f"TikTok API error: {payload.get('error_description') or error}")
    data = payload.get("data")
    return data if isinstance(data, dict) else {}


def _save_tokens(payload: dict[str, Any]) -> dict[str, Any]:
    now = int(time.time())
    tokens = {
        "access_token": payload["access_token"],
        "refresh_token": payload.get("refresh_token", ""),
        "open_id": payload.get("open_id", ""),
        "scope": payload.get("scope", ""),
        "expires_at": now + int(payload.get("expires_in") or 0),
        "refresh_expires_at": now + int(payload.get("refresh_expires_in") or 0),
    }
    path = _token_path()
    path.write_text(json.dumps(tokens, indent=2) + "\n", encoding="utf-8")
    return tokens


def _read_tokens() -> dict[str, Any]:
    path = _token_path()
    if not path.is_file():
        raise SystemExit("No TikTok tokens yet. Run: python scripts/tiktok_upload.py auth")
    return json.loads(path.read_text(encoding="utf-8"))


def _refresh_tokens(tokens: dict[str, Any]) -> dict[str, Any]:
    key, secret, _redirect = _client_credentials()
    refresh = tokens.get("refresh_token") or ""
    if not refresh:
        raise SystemExit("Saved tokens have no refresh_token. Run auth again.")
    payload = _http_json(
        "POST",
        f"{API_BASE}/v2/oauth/token/",
        form={
            "client_key": key,
            "client_secret": secret,
            "grant_type": "refresh_token",
            "refresh_token": refresh,
        },
    )
    if not payload.get("access_token"):
        raise RuntimeError(f"Token refresh failed: {payload}")
    return _save_tokens(payload)


def access_token() -> str:
    tokens = _read_tokens()
    if int(tokens.get("expires_at") or 0) <= int(time.time()) + 60:
        tokens = _refresh_tokens(tokens)
    token = tokens.get("access_token") or ""
    if not token:
        raise SystemExit("Saved tokens are missing access_token. Run auth again.")
    return token


def query_creator(token: str) -> dict[str, Any]:
    payload = _http_json(
        "POST",
        f"{API_BASE}/v2/post/publish/creator_info/query/",
        token=token,
        body={},
    )
    return _api_data(payload)


def resolve_privacy(requested: str, creator: dict[str, Any]) -> str:
    options = [str(item) for item in creator.get("privacy_level_options") or []]
    if requested in options:
        return requested
    if not options:
        raise RuntimeError("creator_info/query returned no privacy_level_options.")
    raise SystemExit(
        f"Privacy {requested} is not allowed for this account.\n"
        f"Allowed: {', '.join(options)}"
    )


def join_caption(parts: list[str], *, limit: int) -> str:
    text = "\n\n".join(part.strip() for part in parts if part and part.strip())
    return _clip_utf16(text, limit)


def caption_from_story(story_path: Path | None, caption: str, hashtags: str, *, limit: int) -> str:
    chunks: list[str] = []
    if story_path is not None:
        story = json.loads(story_path.read_text(encoding="utf-8"))
        title = str(story.get("title") or "").strip()
        hook = str(story.get("hook") or "").strip()
        if title:
            chunks.append(title)
        if hook and hook != title:
            chunks.append(hook)
    if caption.strip():
        chunks.append(caption.strip())
    if hashtags.strip():
        chunks.append(hashtags.strip())
    return join_caption(chunks, limit=limit)


def list_thumbnails(folder: Path) -> list[Path]:
    if not folder.is_dir():
        return []
    found: list[Path] = []
    for path in sorted(folder.iterdir()):
        if not path.is_file():
            continue
        if path.name.lower() in THUMB_EXCLUDE_NAMES:
            continue
        if path.suffix.lower() not in PHOTO_EXTS:
            continue
        found.append(path)
    return found


def pick_thumbnail(folder: Path) -> Path | None:
    choices = list_thumbnails(folder)
    if not choices:
        return None
    return random.choice(choices)


def probe_video_size(path: Path) -> tuple[int, int]:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height",
            "-of",
            "csv=p=0",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    width, height = (int(item) for item in result.stdout.strip().split(",", 1))
    return width, height


def kinocut_cmd(*args: str) -> None:
    kino = _kino_exe()
    if not kino.is_file():
        raise FileNotFoundError(f"Kinocut CLI not found: {kino}")
    _run([str(kino), "--format", "json", *args], quiet=True)


def make_silent_wav(path: Path, seconds: float) -> None:
    _run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=44100:cl=stereo",
            "-t",
            f"{seconds:.3f}",
            str(path),
        ],
        quiet=True,
    )


def prepend_cover_frame(video: Path, still: Path, output: Path) -> None:
    width, height = probe_video_size(video)
    work = output.parent / f".{output.stem}_cover_work"
    work.mkdir(parents=True, exist_ok=True)
    still_clip = work / "still.mp4"
    sized = work / "still_sized.mp4"
    silent = work / "silence.wav"
    voiced = work / "still_audio.mp4"
    try:
        kinocut_cmd("create-from-images", str(still), "-f", str(COVER_FPS), "-o", str(still_clip))
        kinocut_cmd("resize", str(still_clip), "-w", str(width), "--height", str(height), "-o", str(sized))
        make_silent_wav(silent, 1.0 / COVER_FPS)
        kinocut_cmd("add-audio", str(sized), str(silent), "-o", str(voiced))
        kinocut_cmd("merge", str(voiced), str(video), "-o", str(output))
    finally:
        for leftover in (still_clip, sized, silent, voiced):
            if leftover.exists():
                leftover.unlink()
        if work.exists():
            try:
                work.rmdir()
            except OSError:
                pass


def put_file_chunks(upload_url: str, path: Path) -> None:
    total = path.stat().st_size
    if total <= 0:
        raise RuntimeError(f"Video is empty: {path}")
    chunk_size = total if total <= CHUNK_SIZE else CHUNK_SIZE
    sent = 0
    with path.open("rb") as handle:
        while sent < total:
            data = handle.read(min(chunk_size, total - sent))
            if not data:
                break
            first = sent
            last = sent + len(data) - 1
            request = Request(upload_url, data=data, method="PUT")
            request.add_header("Content-Type", "video/mp4")
            request.add_header("Content-Length", str(len(data)))
            request.add_header("Content-Range", f"bytes {first}-{last}/{total}")
            try:
                with urlopen(request, timeout=300) as response:
                    response.read()
            except HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="replace")
                raise RuntimeError(f"Upload PUT failed ({exc.code}): {detail}") from exc
            sent = last + 1
            print(f"  Uploaded {sent}/{total} bytes")


def fetch_status(token: str, publish_id: str) -> dict[str, Any]:
    payload = _http_json(
        "POST",
        f"{API_BASE}/v2/post/publish/status/fetch/",
        token=token,
        body={"publish_id": publish_id},
    )
    return _api_data(payload)


def poll_status(token: str, publish_id: str) -> dict[str, Any]:
    deadline = time.time() + STATUS_TIMEOUT_SEC
    last: dict[str, Any] = {}
    while time.time() < deadline:
        last = fetch_status(token, publish_id)
        status = str(last.get("status") or "")
        print(f"  Status: {status or last}")
        if status in {"PUBLISH_COMPLETE", "FAILED", "SEND_TO_USER_INBOX"}:
            return last
        time.sleep(STATUS_POLL_SEC)
    raise RuntimeError(f"Timed out waiting for publish_id {publish_id}. Last status: {last}")


class _OAuthHandler(BaseHTTPRequestHandler):
    result: dict[str, str] = {}

    def log_message(self, format: str, *args: Any) -> None:
        return

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path not in {"/callback", "/"}:
            self.send_response(404)
            self.end_headers()
            return
        query = parse_qs(parsed.query)
        if query.get("error"):
            _OAuthHandler.result = {
                "error": query.get("error", [""])[0],
                "error_description": query.get("error_description", [""])[0],
            }
            body = b"TikTok login failed. You can close this window."
        else:
            _OAuthHandler.result = {
                "code": query.get("code", [""])[0],
                "state": query.get("state", [""])[0],
                "scopes": query.get("scopes", [""])[0],
            }
            body = b"TikTok login succeeded. You can close this window."
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def cmd_auth(_args: argparse.Namespace) -> int:
    key, secret, redirect = _client_credentials()
    parsed = urlparse(redirect)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 8787
    verifier, challenge = _pkce_pair()
    state = secrets.token_urlsafe(16)
    params = {
        "client_key": key,
        "response_type": "code",
        "scope": DEFAULT_SCOPES,
        "redirect_uri": redirect,
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    authorize = f"{AUTHORIZE_URL}?{urlencode(params)}"
    _OAuthHandler.result = {}
    server = HTTPServer((host, port), _OAuthHandler)
    print(f"Opening TikTok login. Waiting on {redirect}")
    print(authorize)
    webbrowser.open(authorize)
    while not _OAuthHandler.result:
        server.handle_request()
    server.server_close()
    result = _OAuthHandler.result
    if result.get("error"):
        raise SystemExit(f"TikTok denied login: {result.get('error_description') or result['error']}")
    if result.get("state") != state:
        raise SystemExit("OAuth state mismatch. Try auth again.")
    code = result.get("code") or ""
    if not code:
        raise SystemExit("TikTok callback had no authorization code.")
    payload = _http_json(
        "POST",
        f"{API_BASE}/v2/oauth/token/",
        form={
            "client_key": key,
            "client_secret": secret,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": redirect,
            "code_verifier": verifier,
        },
    )
    if not payload.get("access_token"):
        raise RuntimeError(f"Token exchange failed: {payload}")
    tokens = _save_tokens(payload)
    print(f"Saved tokens to {_token_path()}")
    print(f"open_id: {tokens.get('open_id')}")
    print(f"scope: {tokens.get('scope')}")
    return 0


def cmd_video(args: argparse.Namespace) -> int:
    video = args.video.expanduser().resolve()
    if not video.is_file():
        raise SystemExit(f"Video not found: {video}")
    caption = caption_from_story(args.story_file, args.caption, args.hashtags, limit=VIDEO_CAPTION_LIMIT)
    thumb_dir = args.thumbnail_dir.expanduser()
    if not thumb_dir.is_absolute():
        thumb_dir = (_project_root() / thumb_dir).resolve()
    still = pick_thumbnail(thumb_dir)
    upload_path = video
    cover_note = "first frame (no stills found)"
    if still is not None:
        cover_note = str(still)
        if not args.dry_run:
            print(f"Cover still: {still}")
            upload_path = video.with_name(f"{video.stem}_tiktok_cover.mp4")
            prepend_cover_frame(video, still, upload_path)
    body = {
        "post_info": {
            "title": caption,
            "privacy_level": args.privacy,
            "disable_duet": False,
            "disable_comment": False,
            "disable_stitch": False,
            "video_cover_timestamp_ms": COVER_FRAME_MS,
            "brand_content_toggle": False,
            "brand_organic_toggle": False,
            "is_aigc": True,
        },
        "source_info": {
            "source": "FILE_UPLOAD",
            "video_size": upload_path.stat().st_size if upload_path.is_file() else video.stat().st_size,
            "chunk_size": min(CHUNK_SIZE, upload_path.stat().st_size if upload_path.is_file() else video.stat().st_size)
            or CHUNK_SIZE,
            "total_chunk_count": 1,
        },
    }
    size = int(body["source_info"]["video_size"])
    chunk = CHUNK_SIZE if size > CHUNK_SIZE else size
    body["source_info"]["chunk_size"] = chunk
    body["source_info"]["total_chunk_count"] = max(1, (size + chunk - 1) // chunk) if chunk else 1
    print(f"Caption:\n{caption}\n")
    print(f"Cover: {cover_note}")
    print(f"Privacy: {args.privacy}")
    if args.dry_run:
        print(json.dumps(body, indent=2))
        return 0
    token = access_token()
    creator = query_creator(token)
    privacy = resolve_privacy(args.privacy, creator)
    body["post_info"]["privacy_level"] = privacy
    print(f"Posting as @{creator.get('creator_username') or 'unknown'} ({privacy})")
    init = _api_data(
        _http_json(
            "POST",
            f"{API_BASE}/v2/post/publish/video/init/",
            token=token,
            body=body,
        )
    )
    publish_id = str(init.get("publish_id") or "")
    upload_url = str(init.get("upload_url") or "")
    if not publish_id or not upload_url:
        raise RuntimeError(f"video/init missing publish_id or upload_url: {init}")
    print(f"publish_id: {publish_id}")
    put_file_chunks(upload_url, upload_path)
    if upload_path != video and upload_path.exists():
        upload_path.unlink()
    status = poll_status(token, publish_id)
    print(json.dumps(status, indent=2))
    return 0 if str(status.get("status")) != "FAILED" else 1


def cmd_photo(args: argparse.Namespace) -> int:
    urls = [url.strip() for url in args.image_url if url and url.strip()]
    if not urls:
        raise SystemExit("Pass at least one --image-url. Photo posts cannot use local files.")
    if len(urls) > PHOTO_MAX_IMAGES:
        raise SystemExit(f"TikTok allows at most {PHOTO_MAX_IMAGES} photos.")
    title = _clip_utf16(args.title.strip(), PHOTO_TITLE_LIMIT)
    description = join_caption([args.description, args.hashtags], limit=PHOTO_DESCRIPTION_LIMIT)
    cover_index = args.cover_index
    if cover_index < 0 or cover_index >= len(urls):
        raise SystemExit(f"--cover-index {cover_index} is out of range for {len(urls)} image(s).")
    body = {
        "post_info": {
            "title": title,
            "description": description,
            "privacy_level": args.privacy,
            "disable_comment": False,
            "auto_add_music": True,
            "brand_content_toggle": False,
            "brand_organic_toggle": False,
        },
        "source_info": {
            "source": "PULL_FROM_URL",
            "photo_cover_index": cover_index,
            "photo_images": urls,
        },
        "post_mode": "DIRECT_POST",
        "media_type": "PHOTO",
        "is_aigc": True,
    }
    print(f"Title: {title}")
    print(f"Description:\n{description}\n")
    print(f"Images: {len(urls)} (cover index {cover_index})")
    print("Music: TikTok auto-pick (change it later in the app)")
    if args.dry_run:
        print(json.dumps(body, indent=2))
        return 0
    token = access_token()
    creator = query_creator(token)
    privacy = resolve_privacy(args.privacy, creator)
    body["post_info"]["privacy_level"] = privacy
    print(f"Posting as @{creator.get('creator_username') or 'unknown'} ({privacy})")
    init = _api_data(
        _http_json(
            "POST",
            f"{API_BASE}/v2/post/publish/content/init/",
            token=token,
            body=body,
        )
    )
    publish_id = str(init.get("publish_id") or "")
    if not publish_id:
        raise RuntimeError(f"content/init missing publish_id: {init}")
    print(f"publish_id: {publish_id}")
    status = poll_status(token, publish_id)
    print(json.dumps(status, indent=2))
    print(
        "Music was auto-picked by TikTok. Open the post in the TikTok app "
        "and change the sound if you want a different track."
    )
    return 0 if str(status.get("status")) != "FAILED" else 1


def cmd_status(args: argparse.Namespace) -> int:
    token = access_token()
    status = fetch_status(token, args.publish_id)
    print(json.dumps(status, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Upload videos and photos through TikTok's official Content Posting API."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("auth", help="Open TikTok login and save tokens locally")

    video = sub.add_parser("video", help="Upload a local video with a random still as the cover")
    video.add_argument("video", type=Path, help="Local mp4 to upload")
    video.add_argument("--story-file", type=Path, help="story.json; uses title + hook as the caption")
    video.add_argument("--caption", default="", help="Caption text (used with or instead of story.json)")
    video.add_argument("--hashtags", default="", help='Hashtags, e.g. "#fyp #storytime"')
    video.add_argument(
        "--thumbnail-dir",
        type=Path,
        default=DEFAULT_THUMB_DIR,
        help="Folder of stills to pick a random cover from (default: prompts/dark-luxury-still)",
    )
    video.add_argument("--privacy", choices=PRIVACY_CHOICES, default="SELF_ONLY")
    video.add_argument("--dry-run", action="store_true", help="Print the request body and skip TikTok")

    photo = sub.add_parser("photo", help="Post hosted photos; TikTok auto-picks the music")
    photo.add_argument(
        "--image-url",
        action="append",
        default=[],
        help="Public image URL on a verified prefix. Repeat for a carousel (max 35).",
    )
    photo.add_argument("--title", default="", help="Photo title (max 90 characters)")
    photo.add_argument("--description", default="", help="Photo description")
    photo.add_argument("--hashtags", default="", help='Hashtags appended to the description')
    photo.add_argument("--cover-index", type=int, default=0, help="Which image is the cover (default: 0)")
    photo.add_argument("--privacy", choices=PRIVACY_CHOICES, default="SELF_ONLY")
    photo.add_argument("--dry-run", action="store_true", help="Print the request body and skip TikTok")

    status = sub.add_parser("status", help="Fetch a publish_id status")
    status.add_argument("--publish-id", required=True, help="publish_id from a previous upload")
    return parser


def main() -> int:
    _load_env()
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    args = build_parser().parse_args()
    commands = {
        "auth": cmd_auth,
        "video": cmd_video,
        "photo": cmd_photo,
        "status": cmd_status,
    }
    try:
        return commands[args.command](args)
    except RuntimeError as exc:
        print(exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
