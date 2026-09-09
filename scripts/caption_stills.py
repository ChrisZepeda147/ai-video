#!/usr/bin/env python3
"""Burn centered captions onto stills. Does not overwrite the source files."""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
PENTHOUSE = ROOT / "prompts" / "dark-luxury-still" / "nyc-penthouse"
FONT_PATH = Path(r"C:\Windows\Fonts\arialbd.ttf")
INK = (255, 255, 255)
OUTLINE = (0, 0, 0)

# Same story, laid out like the reference: numbered rule, sentence case, 3 lines.
# place is where the text block sits: top/mid/bottom + left/center/right
WINTER_ARC = [
    (
        "nyc-penthouse-living-dusk.png",
        "1. Stay in when the city is loud. That's the winter arc.",
        "top-center",
    ),
    (
        "nyc-penthouse-kitchen-dusk.png",
        "2. Eat the same thing. Stop negotiating with yourself.",
        "bottom-left",
    ),
    (
        "nyc-penthouse-bedroom-dusk.png",
        "3. Sleep on time. Leave the phone in the other room.",
        "mid-left",
    ),
    (
        "nyc-penthouse-terrace-dusk.png",
        "4. Train in the cold. Nobody is watching you.",
        "bottom-right",
    ),
    (
        "nyc-penthouse-bath-dusk.png",
        "5. Wake up and do it again. Don't wait to feel ready.",
        "top-right",
    ),
    (
        "nyc-penthouse-dining-dusk.png",
        "6. Lock in. That's the whole story.",
        "bottom-center",
    ),
]


def _font(size: int) -> ImageFont.FreeTypeFont:
    if FONT_PATH.is_file():
        return ImageFont.truetype(str(FONT_PATH), size)
    return ImageFont.truetype("arialbd.ttf", size)


def _wrap(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_width: float) -> str:
    words = text.split()
    lines: list[str] = []
    current: list[str] = []
    for word in words:
        trial = " ".join(current + [word])
        box = draw.textbbox((0, 0), trial, font=font)
        if current and (box[2] - box[0]) > max_width:
            lines.append(" ".join(current))
            current = [word]
        else:
            current.append(word)
    if current:
        lines.append(" ".join(current))
    return "\n".join(lines)


def _text_size(
    draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, spacing: int, align: str
) -> tuple[int, int]:
    box = draw.multiline_textbbox((0, 0), text, font=font, align=align, spacing=spacing)
    return box[2] - box[0], box[3] - box[1]


def _anchor(width: int, height: int, text_w: int, text_h: int, place: str) -> tuple[float, float]:
    mx = width * 0.08
    my = height * 0.10
    x_map = {
        "left": mx,
        "center": (width - text_w) / 2,
        "right": width - mx - text_w,
    }
    y_map = {
        "top": height * 0.14,
        "mid": height * 0.30,
        "bottom": height - my - text_h,
    }
    y_name, x_name = place.split("-", 1)
    return x_map[x_name], y_map[y_name]


def _draw_outlined(
    draw: ImageDraw.ImageDraw,
    xy: tuple[float, float],
    text: str,
    font: ImageFont.FreeTypeFont,
    *,
    stroke: int,
    spacing: int,
    align: str,
) -> None:
    x, y = xy
    for dx in range(-stroke, stroke + 1):
        for dy in range(-stroke, stroke + 1):
            if dx == 0 and dy == 0:
                continue
            draw.multiline_text((x + dx, y + dy), text, font=font, fill=OUTLINE, align=align, spacing=spacing)
    draw.multiline_text((x, y), text, font=font, fill=INK, align=align, spacing=spacing)


def caption_image(src: Path, dest: Path, caption: str, place: str) -> None:
    img = Image.open(src).convert("RGB")
    width, height = img.size
    # Measured from the reference still: ~17px type on 1024-tall, ~30% frame width.
    font = _font(max(16, round(height * 17 / 1024)))
    spacing = max(4, round(height * 8 / 1024))
    align = "center" if place.endswith("center") else "left"
    probe = ImageDraw.Draw(img)
    wrapped = _wrap(probe, caption, font, width * 0.32)
    text_w, text_h = _text_size(probe, wrapped, font, spacing, align)
    left, top = _anchor(width, height, text_w, text_h, place)
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    stroke = max(1, round(width * 2 / 684))
    _draw_outlined(draw, (left, top), wrapped, font, stroke=stroke, spacing=spacing, align=align)
    composed = Image.alpha_composite(img.convert("RGBA"), overlay)
    dest.parent.mkdir(parents=True, exist_ok=True)
    composed.convert("RGB").save(dest, "PNG")


def main() -> int:
    parser = argparse.ArgumentParser(description="Add centered captions to stills.")
    parser.add_argument("--series", default="winter-arc", help="Caption series (default: winter-arc)")
    args = parser.parse_args()
    if args.series != "winter-arc":
        raise SystemExit(f"Unknown series: {args.series}")
    out_dir = PENTHOUSE / "captioned"
    for name, caption, place in WINTER_ARC:
        src = PENTHOUSE / name
        if not src.is_file():
            raise SystemExit(f"Missing still: {src}")
        dest = out_dir / name
        caption_image(src, dest, caption, place)
        print(f"Wrote {dest.relative_to(ROOT)} ({place})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
