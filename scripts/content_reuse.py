#!/usr/bin/env python3
"""
Catalog and reuse check for photos, videos, and stories you have already made.

Scans created stills, rendered videos, and story.json files, then keeps a
persistent ledger at content/used.json so deleted downloads are still remembered.

Examples:
  python scripts/content_reuse.py rebuild
  python scripts/content_reuse.py list
  python scripts/content_reuse.py check-story --file downloads/imessage/new/story.json
  python scripts/content_reuse.py check-photo --slug white-yacht-midnight
  python scripts/content_reuse.py check-video --youtube-id p0aHDT8wwrw
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

STOPWORDS = {
    "a", "about", "after", "again", "all", "already", "also", "am", "an", "and",
    "are", "as", "at", "back", "be", "because", "been", "before", "but", "by",
    "call", "came", "can", "could", "did", "do", "does", "down", "even", "every",
    "for", "from", "get", "got", "had", "has", "have", "he", "her", "here",
    "him", "his", "how", "i", "if", "im", "in", "into", "is", "it", "its",
    "just", "keep", "knew", "know", "like", "look", "me", "my", "never", "no",
    "not", "now", "of", "off", "on", "one", "or", "out", "over", "said", "she",
    "so", "still", "that", "the", "their", "them", "then", "there", "they",
    "this", "to", "told", "too", "up", "was", "we", "were", "what", "when",
    "where", "who", "why", "with", "would", "you", "your",
}

PHOTO_EXTS = {".png", ".jpg", ".jpeg", ".webp"}
VIDEO_EXTS = {".mp4", ".mov", ".webm"}
YOUTUBE_ID_RE = re.compile(r"^([A-Za-z0-9_-]{11})_(?:part\d+|source|16x9)", re.IGNORECASE)
SLUG_RE = re.compile(r"[^a-z0-9]+")
WORD_RE = re.compile(r"[a-z0-9']+")

STORY_TITLE_THRESHOLD = 0.72
STORY_TOKEN_THRESHOLD = 0.34
STORY_OVERLAP_THRESHOLD = 0.55
STORY_OVERLAP_MIN_SHARED = 8
PHOTO_TOKEN_THRESHOLD = 0.82

PHOTO_EXCLUDE_NAMES = {"reference.png"}
PHOTO_EXCLUDE_DIRS = {"references"}


@dataclass
class ReuseHit:
    kind: str
    id: str
    title: str
    reason: str
    score: float = 1.0
    path: str = ""


@dataclass
class Catalog:
    updated_at: str = ""
    photos: list[dict[str, Any]] = field(default_factory=list)
    videos: list[dict[str, Any]] = field(default_factory=list)
    stories: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "updated_at": self.updated_at,
            "photos": self.photos,
            "videos": self.videos,
            "stories": self.stories,
        }


class StoryReuseError(ValueError):
    def __init__(self, hits: list[ReuseHit]):
        self.hits = hits
        super().__init__(format_hits(hits))


def project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def catalog_path(root: Path | None = None) -> Path:
    return (root or project_root()) / "content" / "used.json"


def rel_path(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def file_sha256(path: Path, *, limit: int = 32 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    read = 0
    with path.open("rb") as handle:
        while read < limit:
            chunk = handle.read(min(1024 * 1024, limit - read))
            if not chunk:
                break
            digest.update(chunk)
            read += len(chunk)
    return digest.hexdigest()


def slugify(text: str) -> str:
    slug = SLUG_RE.sub("-", (text or "").lower()).strip("-")
    return slug or "untitled"


def normalize_text(text: str) -> str:
    return " ".join(WORD_RE.findall((text or "").lower()))


def tokens(text: str) -> set[str]:
    return {word for word in WORD_RE.findall((text or "").lower()) if word not in STOPWORDS and len(word) > 2}


def jaccard(left: Iterable[str], right: Iterable[str]) -> float:
    a = set(left)
    b = set(right)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def overlap_coef(left: Iterable[str], right: Iterable[str]) -> tuple[float, int]:
    a = set(left)
    b = set(right)
    if not a or not b:
        return 0.0, 0
    shared = len(a & b)
    return shared / min(len(a), len(b)), shared


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def load_persisted(root: Path | None = None) -> Catalog:
    path = catalog_path(root)
    if not path.is_file():
        return Catalog()
    data = json.loads(path.read_text(encoding="utf-8"))
    return Catalog(
        updated_at=str(data.get("updated_at") or ""),
        photos=list(data.get("photos") or []),
        videos=list(data.get("videos") or []),
        stories=list(data.get("stories") or []),
    )


def save_catalog(catalog: Catalog, root: Path | None = None) -> Path:
    path = catalog_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    catalog.updated_at = now_iso()
    path.write_text(json.dumps(catalog.to_dict(), indent=2), encoding="utf-8")
    return path


def _merge_by_id(old_rows: list[dict[str, Any]], new_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for row in old_rows:
        key = str(row.get("id") or "")
        if key:
            merged[key] = row
    for row in new_rows:
        key = str(row.get("id") or "")
        if key:
            merged[key] = {**merged.get(key, {}), **row}
    return list(merged.values())


def merge_catalogs(persisted: Catalog, live: Catalog) -> Catalog:
    return Catalog(
        updated_at=now_iso(),
        photos=_merge_by_id(persisted.photos, live.photos),
        videos=_merge_by_id(persisted.videos, live.videos),
        stories=_merge_by_id(persisted.stories, live.stories),
    )


def current_catalog(root: Path | None = None) -> Catalog:
    base = root or project_root()
    return merge_catalogs(load_persisted(base), scan_project(base))


def story_blob(story: dict[str, Any]) -> str:
    chunks = [
        str(story.get("title") or ""),
        str(story.get("hook") or ""),
        str(story.get("contact_name") or ""),
        str(story.get("theme") or ""),
    ]
    for part in story.get("parts") or []:
        if not isinstance(part, dict):
            continue
        chunks.append(str(part.get("narration") or ""))
        for message in part.get("messages") or []:
            if isinstance(message, dict):
                chunks.append(str(message.get("text") or ""))
    return " ".join(chunk for chunk in chunks if chunk)


def story_summary(story: dict[str, Any]) -> str:
    hook = str(story.get("hook") or "").strip()
    if hook:
        return hook
    for part in story.get("parts") or []:
        if isinstance(part, dict):
            narration = str(part.get("narration") or "").strip()
            if narration:
                sentence = re.split(r"(?<=[.!?])\s+", narration, maxsplit=1)[0]
                return sentence[:180]
    return str(story.get("title") or "Untitled story")


def story_record(story: dict[str, Any], *, path: str, slug: str) -> dict[str, Any]:
    title = str(story.get("title") or slug)
    token_list = sorted(tokens(story_blob(story)))
    return {
        "id": f"story:{slug}",
        "kind": "story",
        "path": path,
        "slug": slug,
        "title": title,
        "hook": str(story.get("hook") or ""),
        "summary": story_summary(story),
        "title_norm": normalize_text(title),
        "hook_norm": normalize_text(str(story.get("hook") or "")),
        "tokens": token_list,
    }


def photo_record(path: Path, root: Path) -> dict[str, Any]:
    slug = slugify(path.stem)
    return {
        "id": f"photo:{slug}",
        "kind": "photo",
        "path": rel_path(path, root),
        "slug": slug,
        "title": path.stem.replace("-", " "),
        "tokens": sorted(tokens(path.stem.replace("-", " ").replace("_", " "))),
        "sha256": file_sha256(path),
    }


def youtube_id_from_name(name: str) -> str | None:
    match = YOUTUBE_ID_RE.match(name)
    return match.group(1) if match else None


def video_record(path: Path, root: Path, *, youtube_id: str | None = None, extra_paths: list[str] | None = None) -> dict[str, Any]:
    yt = youtube_id or youtube_id_from_name(path.name)
    folder_label = path.parent.name if path.name.startswith("part") else path.stem
    slug = yt or slugify(folder_label)
    video_id = f"video:{yt}" if yt else f"video:{slug}"
    title = yt or folder_label.replace("_", " ")
    return {
        "id": video_id,
        "kind": "video",
        "path": rel_path(path, root),
        "paths": extra_paths or [rel_path(path, root)],
        "slug": slug,
        "title": title,
        "youtube_id": yt,
        "sha256": file_sha256(path),
    }


def scan_photos(root: Path) -> list[dict[str, Any]]:
    folder = root / "prompts" / "dark-luxury-still"
    if not folder.is_dir():
        return []
    rows: list[dict[str, Any]] = []
    for path in sorted(folder.iterdir()):
        if not path.is_file() or path.suffix.lower() not in PHOTO_EXTS:
            continue
        if path.name.lower() in PHOTO_EXCLUDE_NAMES:
            continue
        rows.append(photo_record(path, root))
    return rows


def scan_stories(root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for path in sorted((root / "downloads").rglob("story.json")) if (root / "downloads").is_dir() else []:
        try:
            story = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(story, dict):
            continue
        slug = slugify(str(story.get("title") or path.parent.name))
        if path.parent.name not in {"final", "imessage", "youtube", "downloads"}:
            slug = slugify(path.parent.name)
        key = f"{slug}:{rel_path(path, root)}"
        if key in seen:
            continue
        seen.add(key)
        rows.append(story_record(story, path=rel_path(path, root), slug=slug))
    return rows


def scan_videos(root: Path) -> list[dict[str, Any]]:
    downloads = root / "downloads"
    if not downloads.is_dir():
        return []
    grouped: dict[str, list[Path]] = {}
    for path in sorted(downloads.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in VIDEO_EXTS:
            continue
        yt = youtube_id_from_name(path.name)
        key = yt or rel_path(path.parent if path.name.startswith("part") else path, root)
        grouped.setdefault(key, []).append(path)

    rows: list[dict[str, Any]] = []
    for key, paths in grouped.items():
        first = paths[0]
        yt = youtube_id_from_name(first.name) if len(key) == 11 else None
        if youtube_id_from_name(first.name):
            yt = youtube_id_from_name(first.name)
        rows.append(
            video_record(
                first,
                root,
                youtube_id=yt,
                extra_paths=[rel_path(item, root) for item in paths],
            )
        )
    return rows


def scan_project(root: Path | None = None) -> Catalog:
    base = root or project_root()
    return Catalog(
        updated_at=now_iso(),
        photos=scan_photos(base),
        videos=scan_videos(base),
        stories=scan_stories(base),
    )


def rebuild(root: Path | None = None) -> tuple[Catalog, Path]:
    base = root or project_root()
    catalog = current_catalog(base)
    path = save_catalog(catalog, base)
    return catalog, path


def _ignore(path: str, ignore_paths: set[str] | None) -> bool:
    if not ignore_paths or not path:
        return False
    normalized = path.replace("\\", "/").lower()
    for item in ignore_paths:
        other = str(item).replace("\\", "/").lower()
        if normalized == other:
            return True
        if normalized.endswith(other) or other.endswith(normalized):
            return True
    return False


def find_story_reuse(
    story: dict[str, Any],
    *,
    catalog: Catalog | None = None,
    ignore_paths: Iterable[str] | None = None,
    root: Path | None = None,
) -> list[ReuseHit]:
    catalog = catalog or current_catalog(root)
    ignore = {str(item) for item in (ignore_paths or [])}
    title_norm = normalize_text(str(story.get("title") or ""))
    hook_norm = normalize_text(str(story.get("hook") or ""))
    story_tokens = tokens(story_blob(story))
    hits: list[ReuseHit] = []

    for row in catalog.stories:
        if _ignore(str(row.get("path") or ""), ignore):
            continue
        reasons: list[str] = []
        score = 0.0
        existing_title = normalize_text(str(row.get("title_norm") or row.get("title") or ""))
        existing_hook = normalize_text(str(row.get("hook_norm") or row.get("hook") or ""))
        existing_tokens = set(row.get("tokens") or [])
        title_score = jaccard(title_norm.split(), existing_title.split()) if title_norm and existing_title else 0.0
        hook_score = 1.0 if hook_norm and hook_norm == existing_hook else jaccard(hook_norm.split(), existing_hook.split())
        token_score = jaccard(story_tokens, existing_tokens)
        overlap_score, shared = overlap_coef(story_tokens, existing_tokens)

        if title_norm and title_norm == existing_title:
            reasons.append("same title")
            score = max(score, 1.0)
        elif title_score >= STORY_TITLE_THRESHOLD:
            reasons.append(f"title overlap {title_score:.2f}")
            score = max(score, title_score)
        if hook_norm and hook_norm == existing_hook:
            reasons.append("same hook")
            score = max(score, 1.0)
        elif hook_score >= 0.8:
            reasons.append(f"hook overlap {hook_score:.2f}")
            score = max(score, hook_score)
        if token_score >= STORY_TOKEN_THRESHOLD:
            reasons.append(f"plot overlap {token_score:.2f}")
            score = max(score, token_score)
        elif overlap_score >= STORY_OVERLAP_THRESHOLD and shared >= STORY_OVERLAP_MIN_SHARED:
            reasons.append(f"plot overlap {overlap_score:.2f} ({shared} shared details)")
            score = max(score, overlap_score)
        if reasons:
            hits.append(
                ReuseHit(
                    kind="story",
                    id=str(row.get("id") or ""),
                    title=str(row.get("title") or row.get("slug") or "story"),
                    reason="; ".join(reasons),
                    score=score,
                    path=str(row.get("path") or ""),
                )
            )
    hits.sort(key=lambda item: item.score, reverse=True)
    return hits


def find_photo_reuse(
    *,
    slug: str = "",
    subject: str = "",
    file_path: Path | None = None,
    catalog: Catalog | None = None,
    ignore_paths: Iterable[str] | None = None,
    root: Path | None = None,
) -> list[ReuseHit]:
    catalog = catalog or current_catalog(root)
    ignore = {str(item) for item in (ignore_paths or [])}
    want_slug = slugify(slug or (file_path.stem if file_path else ""))
    want_tokens = tokens(" ".join(part for part in (slug.replace("-", " "), subject) if part))
    want_hash = file_sha256(file_path) if file_path and file_path.is_file() else ""
    hits: list[ReuseHit] = []

    for row in catalog.photos:
        if _ignore(str(row.get("path") or ""), ignore):
            continue
        reasons: list[str] = []
        score = 0.0
        if want_hash and want_hash == row.get("sha256"):
            reasons.append("same image file")
            score = 1.0
        if want_slug and want_slug == row.get("slug"):
            reasons.append("same still slug")
            score = max(score, 1.0)
        token_score = jaccard(want_tokens, set(row.get("tokens") or []))
        if token_score >= PHOTO_TOKEN_THRESHOLD:
            reasons.append(f"same subject {token_score:.2f}")
            score = max(score, token_score)
        if reasons:
            hits.append(
                ReuseHit(
                    kind="photo",
                    id=str(row.get("id") or ""),
                    title=str(row.get("title") or row.get("slug") or "photo"),
                    reason="; ".join(reasons),
                    score=score,
                    path=str(row.get("path") or ""),
                )
            )
    hits.sort(key=lambda item: item.score, reverse=True)
    return hits


def find_video_reuse(
    *,
    youtube_id: str = "",
    file_path: Path | None = None,
    catalog: Catalog | None = None,
    ignore_paths: Iterable[str] | None = None,
    root: Path | None = None,
) -> list[ReuseHit]:
    catalog = catalog or current_catalog(root)
    ignore = {str(item) for item in (ignore_paths or [])}
    yt = (youtube_id or (youtube_id_from_name(file_path.name) if file_path else "") or "").strip()
    want_hash = file_sha256(file_path) if file_path and file_path.is_file() else ""
    hits: list[ReuseHit] = []

    for row in catalog.videos:
        paths = [str(row.get("path") or ""), *(row.get("paths") or [])]
        if any(_ignore(item, ignore) for item in paths):
            continue
        reasons: list[str] = []
        if yt and yt == row.get("youtube_id"):
            reasons.append(f"already used YouTube id {yt}")
        if want_hash and want_hash == row.get("sha256"):
            reasons.append("same video file")
        if reasons:
            hits.append(
                ReuseHit(
                    kind="video",
                    id=str(row.get("id") or ""),
                    title=str(row.get("title") or row.get("youtube_id") or "video"),
                    reason="; ".join(reasons),
                    score=1.0,
                    path=str(row.get("path") or ""),
                )
            )
    return hits


def used_youtube_ids(catalog: Catalog | None = None, root: Path | None = None) -> set[str]:
    catalog = catalog or current_catalog(root)
    return {str(row["youtube_id"]) for row in catalog.videos if row.get("youtube_id")}


def enforce_story_unused(
    story: dict[str, Any],
    *,
    ignore_paths: Iterable[str] | None = None,
    allow_reuse: bool = False,
    root: Path | None = None,
) -> list[ReuseHit]:
    hits = find_story_reuse(story, ignore_paths=ignore_paths, root=root)
    if hits and not allow_reuse:
        raise StoryReuseError(hits)
    return hits


def register_story(story: dict[str, Any], *, path: Path, root: Path | None = None) -> Catalog:
    base = root or project_root()
    catalog = current_catalog(base)
    slug = slugify(path.parent.name if path.parent.name not in {"final", "imessage", "youtube"} else str(story.get("title") or path.parent.name))
    record = story_record(story, path=rel_path(path, base), slug=slug)
    catalog.stories = _merge_by_id(catalog.stories, [record])
    save_catalog(catalog, base)
    return catalog


def register_video(
    *,
    youtube_id: str = "",
    file_path: Path | None = None,
    title: str = "",
    root: Path | None = None,
) -> Catalog:
    base = root or project_root()
    catalog = current_catalog(base)
    if file_path and file_path.is_file():
        record = video_record(file_path, base, youtube_id=youtube_id or None)
    else:
        yt = youtube_id.strip()
        record = {
            "id": f"video:{yt}" if yt else f"video:{slugify(title or 'video')}",
            "kind": "video",
            "path": "",
            "paths": [],
            "slug": yt or slugify(title or "video"),
            "title": title or yt or "video",
            "youtube_id": yt or None,
            "sha256": "",
        }
    if title:
        record["title"] = title
    catalog.videos = _merge_by_id(catalog.videos, [record])
    save_catalog(catalog, base)
    return catalog


def register_photo(path: Path, root: Path | None = None) -> Catalog:
    base = root or project_root()
    catalog = current_catalog(base)
    catalog.photos = _merge_by_id(catalog.photos, [photo_record(path, base)])
    save_catalog(catalog, base)
    return catalog


def format_hits(hits: list[ReuseHit]) -> str:
    if not hits:
        return "No reuse found."
    lines = ["This reuses content you already made:"]
    for hit in hits:
        where = f" ({hit.path})" if hit.path else ""
        lines.append(f"  - [{hit.kind}] {hit.title}{where}: {hit.reason}")
    return "\n".join(lines)


def used_prompt_block(catalog: Catalog | None = None, root: Path | None = None) -> str:
    catalog = catalog or current_catalog(root)
    if not (catalog.stories or catalog.photos or catalog.videos):
        return ""
    lines = [
        "## Already used — do not repeat",
        "Create something new. Do not reuse these plots, titles, hooks, stills, or source videos.",
        "",
    ]
    if catalog.stories:
        lines.append("Stories:")
        for row in catalog.stories:
            title = row.get("title") or row.get("slug")
            summary = row.get("summary") or row.get("hook") or ""
            lines.append(f"- {title} — {summary}" if summary else f"- {title}")
        lines.append("")
    if catalog.photos:
        lines.append("Photos:")
        for row in catalog.photos:
            lines.append(f"- {row.get('slug')} ({row.get('path')})")
        lines.append("")
    if catalog.videos:
        lines.append("Videos:")
        for row in catalog.videos:
            yt = row.get("youtube_id")
            label = f"YouTube {yt}" if yt else row.get("title") or row.get("slug")
            lines.append(f"- {label}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def print_catalog(catalog: Catalog) -> None:
    print(f"Updated: {catalog.updated_at or '(not saved yet)'}")
    print(f"\nStories ({len(catalog.stories)}):")
    if not catalog.stories:
        print("  (none)")
    for row in catalog.stories:
        print(f"  - {row.get('title')}  [{row.get('slug')}]")
        if row.get("summary"):
            print(f"    {row['summary']}")
    print(f"\nPhotos ({len(catalog.photos)}):")
    if not catalog.photos:
        print("  (none)")
    for row in catalog.photos:
        print(f"  - {row.get('slug')}  ({row.get('path')})")
    print(f"\nVideos ({len(catalog.videos)}):")
    if not catalog.videos:
        print("  (none)")
    for row in catalog.videos:
        yt = f"  yt:{row['youtube_id']}" if row.get("youtube_id") else ""
        print(f"  - {row.get('title')}{yt}")
        for path in row.get("paths") or [row.get("path")]:
            if path:
                print(f"    {path}")


def _exit_hits(hits: list[ReuseHit]) -> int:
    if hits:
        print(format_hits(hits), file=sys.stderr)
        return 2
    print("OK — not a reuse of existing content.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Check and catalog used photos, videos, and stories.")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("rebuild", help="Scan created content and update content/used.json")
    listed = sub.add_parser("list", help="Show used photos, videos, and stories")
    listed.add_argument("--json", action="store_true", help="Print catalog JSON")

    story = sub.add_parser("check-story", help="Fail if a story reuses an existing plot/title/hook")
    story.add_argument("--file", type=Path, help="Path to story.json")
    story.add_argument("--title", default="", help="Proposed title")
    story.add_argument("--hook", default="", help="Proposed hook")
    story.add_argument("--text", default="", help="Proposed narration or extra plot text")
    story.add_argument("--allow-reuse", action="store_true")

    photo = sub.add_parser("check-photo", help="Fail if a still matches an existing photo")
    photo.add_argument("--slug", default="", help="Output filename stem, e.g. white-yacht-midnight")
    photo.add_argument("--subject", default="", help="Subject + setting you are about to generate")
    photo.add_argument("--file", type=Path, help="Existing image to compare")
    photo.add_argument("--allow-reuse", action="store_true")

    video = sub.add_parser("check-video", help="Fail if a YouTube id or file was already used")
    video.add_argument("--youtube-id", default="", help="YouTube video id")
    video.add_argument("--file", type=Path, help="Local video file")
    video.add_argument("--allow-reuse", action="store_true")

    return parser


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    args = build_parser().parse_args()
    root = project_root()

    if args.command == "rebuild":
        catalog, path = rebuild(root)
        print(f"Wrote {path}")
        print_catalog(catalog)
        return 0

    if args.command == "list":
        catalog = current_catalog(root)
        if args.json:
            print(json.dumps(catalog.to_dict(), indent=2))
        else:
            print_catalog(catalog)
        return 0

    if args.command == "check-story":
        if args.file:
            story = json.loads(args.file.read_text(encoding="utf-8"))
            ignore = [rel_path(args.file, root), str(args.file)]
        else:
            story = {
                "title": args.title,
                "hook": args.hook,
                "parts": [{"part": 1, "narration": args.text}],
            }
            ignore = []
        hits = find_story_reuse(story, ignore_paths=ignore, root=root)
        if args.allow_reuse:
            if hits:
                print(format_hits(hits))
                print("Allowed by --allow-reuse.")
            else:
                print("OK — not a reuse of existing content.")
            return 0
        return _exit_hits(hits)

    if args.command == "check-photo":
        hits = find_photo_reuse(slug=args.slug, subject=args.subject, file_path=args.file, root=root)
        return 0 if args.allow_reuse else _exit_hits(hits)

    if args.command == "check-video":
        hits = find_video_reuse(youtube_id=args.youtube_id, file_path=args.file, root=root)
        return 0 if args.allow_reuse else _exit_hits(hits)

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
