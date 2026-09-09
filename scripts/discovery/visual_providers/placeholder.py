"""Write minimal valid placeholder images for prompt-export / tests."""

from __future__ import annotations

from pathlib import Path


def write_placeholder_image(
    path: Path,
    *,
    width: int,
    height: int,
    seed: str | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tint = hash(seed or str(path)) & 0xFF
    color = (18 + (tint % 40), 16 + (tint % 20), 24 + (tint % 30))
    try:
        from PIL import Image

        img = Image.new("RGB", (width, height), color=color)
        img.save(path, format="PNG")
        return
    except ImportError:
        pass

    # Fallback without Pillow: valid tiny PNG plus unique suffix so hashes differ per asset.
    unique = (seed or str(path)).encode("utf-8", errors="ignore")
    path.write_bytes(_MINIMAL_PNG + unique)


_MINIMAL_PNG = (
    b"\x89PNG\r\n\x1a\n"
    b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00\x90wS\xde"
    b"\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N"
    b"\x00\x00\x00\x00IEND\xaeB`\x82"
)
