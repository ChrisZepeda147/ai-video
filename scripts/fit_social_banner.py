#!/usr/bin/env python3
"""Fit a still to a social cover. Cover-crop or place the subject in a safe zone.

Examples:
  python scripts/fit_social_banner.py --input photo.jpg --output cover.jpg --preset facebook-cover
  python scripts/fit_social_banner.py --input photo.jpg --output cover.jpg --preset facebook-cover --subject-safe --preview cover-preview.jpg
  python scripts/fit_social_banner.py --input photo.jpg --output banner.jpg --preset youtube-banner --preview banner-preview.jpg --sizes-preview banner-sizes.jpg
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageDraw


@dataclass(frozen=True)
class CropGuide:
    name: str
    left: int
    top: int
    right: int
    bottom: int
    color: tuple[int, int, int]


@dataclass(frozen=True)
class BannerPreset:
    name: str
    width: int
    height: int
    safe_left: int
    safe_top: int
    safe_right: int
    safe_bottom: int
    avatar_cx: int = 0
    avatar_cy: int = 0
    avatar_radius: int = 0
    default_fit: str = "cover"
    extra_crops: tuple[CropGuide, ...] = field(default_factory=tuple)

    @property
    def safe_width(self) -> int:
        return self.safe_right - self.safe_left

    @property
    def safe_height(self) -> int:
        return self.safe_bottom - self.safe_top


# YouTube: upload 2560x1440. Only the center 1546x423 is on every device.
# Desktop = 2560x423 strip. Tablet = 1855x423. Mobile = 1546x423. TV = full frame.
PRESETS: dict[str, BannerPreset] = {
    "facebook-cover": BannerPreset(
        name="facebook-cover",
        width=1640,
        height=624,
        safe_left=266,
        safe_top=0,
        safe_right=1374,
        safe_bottom=624,
        avatar_cx=176,
        avatar_cy=624,
        avatar_radius=176,
        default_fit="cover",
    ),
    "youtube-banner": BannerPreset(
        name="youtube-banner",
        width=2560,
        height=1440,
        safe_left=507,
        safe_top=509,
        safe_right=2053,
        safe_bottom=932,
        default_fit="safe",
        extra_crops=(
            CropGuide("desktop", 0, 509, 2560, 932, (255, 210, 80)),
            CropGuide("tablet", 353, 509, 2208, 932, (180, 140, 255)),
        ),
    ),
}


@dataclass(frozen=True)
class Box:
    left: int
    top: int
    right: int
    bottom: int

    @property
    def width(self) -> int:
        return self.right - self.left

    @property
    def height(self) -> int:
        return self.bottom - self.top

    def shifted(self, dx: int, dy: int = 0) -> Box:
        return Box(self.left + dx, self.top + dy, self.right + dx, self.bottom + dy)


def parse_hex_color(value: str) -> tuple[int, int, int]:
    raw = value.strip().lstrip("#")
    if len(raw) != 6:
        raise ValueError(f"Color must be #RRGGBB, got {value!r}")
    return int(raw[0:2], 16), int(raw[2:4], 16), int(raw[4:6], 16)


def _pink_column_ratio(image: Image.Image, body_bottom: int) -> list[float]:
    pixels = image.load()
    width, _height = image.size
    ratios = [0.0] * width
    for x in range(width):
        hits = 0
        for y in range(body_bottom):
            r, g, b = pixels[x, y][:3]
            if r > 90 and r > g + 20 and r > b + 20:
                hits += 1
        ratios[x] = hits / max(body_bottom, 1)
    return ratios


def _longest_run(flags: list[bool]) -> tuple[int, int] | None:
    best: tuple[int, int] | None = None
    start: int | None = None
    for index, flag in enumerate(flags):
        if flag and start is None:
            start = index
            continue
        if flag or start is None:
            continue
        run = (start, index)
        if best is None or run[1] - run[0] > best[1] - best[0]:
            best = run
        start = None
    if start is not None:
        run = (start, len(flags))
        if best is None or run[1] - run[0] > best[1] - best[0]:
            best = run
    return best


def detect_subject_box(image: Image.Image, *, include_reflection: bool = True) -> Box | None:
    """Pink body plus dark rear wing. Optional mirror on the floor."""
    src = image.convert("RGB")
    width, height = src.size
    body_bottom = int(height * (0.62 if include_reflection else 0.55))
    ratios = _pink_column_ratio(src, body_bottom)
    peak = max(ratios) if ratios else 0.0
    if peak < 0.04:
        return None
    run = _longest_run([value >= max(peak * 0.18, 0.03) for value in ratios])
    if run is None:
        return None
    left, right = run
    pixels = src.load()
    top = height
    bottom = 0
    scan_bottom = height if include_reflection else body_bottom
    for y in range(scan_bottom):
        hit = False
        for x in range(left, right):
            r, g, b = pixels[x, y][:3]
            if y < body_bottom and r > 90 and r > g + 20 and r > b + 20:
                hit = True
                break
            if include_reflection and y >= body_bottom and max(r, g, b) > 28:
                hit = True
                break
        if not hit:
            continue
        top = min(top, y)
        bottom = max(bottom, y + 1)
    if bottom <= top:
        return None
    wing_pad = max(24, int((right - left) * 0.16))
    left = max(0, left - wing_pad)
    top = max(0, top - max(8, (bottom - top) // 20))
    return Box(left=left, top=top, right=min(width, right + 8), bottom=min(height, bottom))


def extend_left_with_scene(image: Image.Image, extra: int) -> Image.Image:
    """Grow the left edge from existing sky/floor pixels. Not a flat bar."""
    if extra <= 0:
        return image.convert("RGB")
    src = image.convert("RGB")
    strip_w = min(64, src.width)
    strip = src.crop((0, 0, strip_w, src.height))
    grown = strip.resize((extra + strip_w, src.height), Image.Resampling.BICUBIC)
    canvas = Image.new("RGB", (src.width + extra, src.height))
    canvas.paste(grown.crop((0, 0, extra, src.height)), (0, 0))
    canvas.paste(src, (extra, 0))
    return canvas


def extend_to_canvas(
    image: Image.Image,
    *,
    width: int,
    height: int,
    paste_x: int,
    paste_y: int,
) -> Image.Image:
    """Place the scene on a larger canvas and grow night from its edges."""
    src = image.convert("RGB")
    canvas = Image.new("RGB", (width, height), (0, 0, 0))
    strip = min(48, max(8, src.width // 8), max(8, src.height // 8))
    top_h = max(0, paste_y)
    left_w = max(0, paste_x)
    bot_y = paste_y + src.height
    right_x = paste_x + src.width
    bot_h = max(0, height - bot_y)
    right_w = max(0, width - right_x)
    if top_h:
        sky = src.crop((0, 0, src.width, strip)).resize((width, top_h), Image.Resampling.BICUBIC)
        canvas.paste(sky, (0, 0))
    if bot_h:
        floor = src.crop((0, src.height - strip, src.width, src.height)).resize(
            (width, bot_h), Image.Resampling.BICUBIC
        )
        canvas.paste(floor, (0, bot_y))
    if left_w:
        left = src.crop((0, 0, strip, src.height)).resize((left_w, src.height), Image.Resampling.BICUBIC)
        canvas.paste(left, (0, paste_y))
    if right_w:
        right = src.crop((src.width - strip, 0, src.width, src.height)).resize(
            (right_w, src.height), Image.Resampling.BICUBIC
        )
        canvas.paste(right, (right_x, paste_y))
    canvas.paste(src, (paste_x, paste_y))
    return canvas


def extra_left_for_safe_zone(
    *,
    src_w: int,
    subject_left: int,
    out_w: int,
    safe_left: int,
    padding: int,
) -> int:
    """Pixels to add on the left so cover-scale parks subject in the safe zone."""
    target = safe_left + padding
    extra = 0
    while extra < src_w:
        scale = out_w / (src_w + extra)
        if (subject_left + extra) * scale >= target:
            return extra
        extra += 8
    return extra


def cover_window(
    *,
    src_w: int,
    src_h: int,
    out_w: int,
    out_h: int,
    subject: Box | None,
    safe_left: int,
    padding: int,
) -> tuple[int, int, float]:
    scale = max(out_w / src_w, out_h / src_h)
    scaled_w = max(out_w, round(src_w * scale))
    scaled_h = max(out_h, round(src_h * scale))
    scale = max(scaled_w / src_w, scaled_h / src_h)
    scaled_w = max(out_w, round(src_w * scale))
    scaled_h = max(out_h, round(src_h * scale))
    max_x = scaled_w - out_w
    max_y = scaled_h - out_h
    crop_x = max_x // 2
    crop_y = max_y // 2
    if subject is None:
        return crop_x, crop_y, scale
    sub_left = round(subject.left * scale)
    sub_top = round(subject.top * scale)
    sub_h = round(subject.height * scale)
    crop_x = min(max_x, max(0, sub_left - (safe_left + padding)))
    crop_y = min(max_y, max(0, sub_top - (out_h - sub_h) // 2))
    return crop_x, crop_y, scale


def cover_reframe(
    image: Image.Image,
    *,
    width: int,
    height: int,
    subject: Box | None,
    padding: int,
    safe_left: int = 0,
) -> tuple[Image.Image, Box | None, int]:
    src = image.convert("RGB")
    crop_x, crop_y, scale = cover_window(
        src_w=src.width,
        src_h=src.height,
        out_w=width,
        out_h=height,
        subject=subject,
        safe_left=safe_left,
        padding=padding,
    )
    scaled = src.resize(
        (max(width, round(src.width * scale)), max(height, round(src.height * scale))),
        Image.Resampling.LANCZOS,
    )
    canvas = scaled.crop((crop_x, crop_y, crop_x + width, crop_y + height))
    new_subject = None
    if subject is not None:
        new_subject = Box(
            left=round(subject.left * scale) - crop_x,
            top=round(subject.top * scale) - crop_y,
            right=round(subject.right * scale) - crop_x,
            bottom=round(subject.bottom * scale) - crop_y,
        )
    return canvas, new_subject, crop_x


def fit_canvas(
    image: Image.Image,
    *,
    width: int,
    height: int,
    mode: str,
    fill: tuple[int, int, int],
) -> Image.Image:
    src = image.convert("RGB")
    if mode == "contain":
        fitted = src.copy()
        fitted.thumbnail((width, height), Image.Resampling.LANCZOS)
        canvas = Image.new("RGB", (width, height), fill)
        canvas.paste(fitted, ((width - fitted.width) // 2, (height - fitted.height) // 2))
        return canvas
    if mode != "cover":
        raise ValueError(f"Unknown fit mode {mode!r}")
    return cover_reframe(src, width=width, height=height, subject=None, padding=0)[0]


def place_in_safe_zone(
    image: Image.Image,
    *,
    preset: BannerPreset,
    subject: Box,
    padding: int,
) -> tuple[Image.Image, Box, int]:
    """Scale so the subject fills the all-device safe rect, then grow the night."""
    src = image.convert("RGB")
    max_w = max(1, preset.safe_width - 2 * padding)
    max_h = max(1, preset.safe_height - 2 * padding)
    scale = min(max_w / max(subject.width, 1), max_h / max(subject.height, 1))
    scaled_w = max(1, round(src.width * scale))
    scaled_h = max(1, round(src.height * scale))
    scaled = src.resize((scaled_w, scaled_h), Image.Resampling.LANCZOS)
    placed = Box(
        left=round(subject.left * scale),
        top=round(subject.top * scale),
        right=round(subject.right * scale),
        bottom=round(subject.bottom * scale),
    )
    extra_x = max_w - placed.width
    extra_y = max_h - placed.height
    dest_left = preset.safe_left + padding + extra_x // 2
    dest_top = preset.safe_top + padding + extra_y // 2
    paste_x = dest_left - placed.left
    paste_y = dest_top - placed.top

    crop_x = max(0, -paste_x)
    crop_y = max(0, -paste_y)
    crop_r = min(scaled_w, crop_x + preset.width)
    crop_b = min(scaled_h, crop_y + preset.height)
    if crop_x or crop_y or crop_r < scaled_w or crop_b < scaled_h:
        scaled = scaled.crop((crop_x, crop_y, crop_r, crop_b))
        placed = placed.shifted(-crop_x, -crop_y)
        paste_x += crop_x
        paste_y += crop_y
    paste_x = max(0, paste_x)
    paste_y = max(0, paste_y)

    canvas = extend_to_canvas(
        scaled,
        width=preset.width,
        height=preset.height,
        paste_x=paste_x,
        paste_y=paste_y,
    )
    return canvas, placed.shifted(paste_x, paste_y), crop_x


def fit_social_banner(
    image: Image.Image,
    *,
    preset: BannerPreset,
    mode: str | None = None,
    fill: tuple[int, int, int] = (0, 0, 0),
    subject_safe: bool = False,
    subject_padding: int = 40,
) -> tuple[Image.Image, Box | None, int]:
    src = image.convert("RGB")
    fit = mode or preset.default_fit
    if fit == "contain" and not subject_safe:
        canvas = fit_canvas(src, width=preset.width, height=preset.height, mode=fit, fill=fill)
        return canvas, detect_subject_box(canvas), 0
    include_reflection = fit != "safe"
    subject = detect_subject_box(src, include_reflection=include_reflection) if (subject_safe or fit == "safe") else None
    if fit == "safe":
        if subject is None:
            subject = Box(0, 0, src.width, src.height)
        return place_in_safe_zone(src, preset=preset, subject=subject, padding=subject_padding)
    if subject_safe and subject is not None:
        extra = extra_left_for_safe_zone(
            src_w=src.width,
            subject_left=subject.left,
            out_w=preset.width,
            safe_left=preset.safe_left,
            padding=subject_padding,
        )
        if extra > 0:
            src = extend_left_with_scene(src, extra)
            subject = subject.shifted(extra)
    return cover_reframe(
        src,
        width=preset.width,
        height=preset.height,
        subject=subject,
        padding=subject_padding,
        safe_left=preset.safe_left,
    )


def _label(draw: ImageDraw.ImageDraw, text: str, xy: tuple[int, int], fill: tuple[int, int, int]) -> None:
    draw.rectangle((xy[0], xy[1], xy[0] + 8 * len(text) + 16, xy[1] + 28), fill=(0, 0, 0, 180))
    draw.text((xy[0] + 8, xy[1] + 6), text, fill=fill)


def draw_preview(image: Image.Image, preset: BannerPreset, subject: Box | None) -> Image.Image:
    preview = image.convert("RGBA")
    overlay = Image.new("RGBA", preview.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay, "RGBA")
    for crop in preset.extra_crops:
        draw.rectangle(
            (crop.left, crop.top, crop.right - 1, crop.bottom - 1),
            outline=(*crop.color, 200),
            width=2,
        )
        label_x = crop.left + 8 if crop.left > 8 else 8
        _label(draw, crop.name, (label_x, crop.top + 8), crop.color)
    draw.rectangle(
        (preset.safe_left, preset.safe_top, preset.safe_right - 1, preset.safe_bottom - 1),
        outline=(0, 255, 180, 230),
        width=3,
    )
    _label(
        draw,
        "safe / mobile",
        (preset.safe_left + 8, min(preset.safe_bottom - 36, preset.safe_top + 8)),
        (0, 255, 180),
    )
    if preset.avatar_radius > 0:
        box = (
            preset.avatar_cx - preset.avatar_radius,
            preset.avatar_cy - preset.avatar_radius,
            preset.avatar_cx + preset.avatar_radius,
            preset.avatar_cy + preset.avatar_radius,
        )
        draw.ellipse(box, fill=(255, 210, 0, 70), outline=(255, 210, 0, 220), width=3)
        _label(draw, "profile pic", (8, preset.height - 40), (255, 210, 0))
    if subject is not None:
        draw.rectangle(
            (subject.left, subject.top, subject.right - 1, subject.bottom - 1),
            outline=(80, 180, 255, 230),
            width=3,
        )
        _label(draw, "full car", (subject.left + 8, max(8, subject.top - 32)), (80, 180, 255))
    return Image.alpha_composite(preview, overlay).convert("RGB")


def draw_sizes_preview(banner: Image.Image, preset: BannerPreset) -> Image.Image:
    """Device crops YouTube / Facebook actually show."""
    pad = 24
    label_h = 36
    tiles: list[tuple[str, Image.Image]] = []
    if preset.name == "youtube-banner":
        tv = banner.resize((preset.width // 4, preset.height // 4), Image.Resampling.LANCZOS)
        tiles.append(("TV 2560x1440 (shown 640x360)", tv))
        desktop = banner.crop((0, preset.safe_top, preset.width, preset.safe_bottom))
        tiles.append(
            (
                "Desktop 2560x423",
                desktop.resize((desktop.width // 2, desktop.height // 2), Image.Resampling.LANCZOS),
            )
        )
        tablet = banner.crop((353, preset.safe_top, 2208, preset.safe_bottom))
        tiles.append(
            (
                "Tablet 1855x423",
                tablet.resize((tablet.width // 2, tablet.height // 2), Image.Resampling.LANCZOS),
            )
        )
        mobile = banner.crop((preset.safe_left, preset.safe_top, preset.safe_right, preset.safe_bottom))
        tiles.append(
            (
                "Mobile / safe 1546x423",
                mobile.resize((mobile.width // 2, mobile.height // 2), Image.Resampling.LANCZOS),
            )
        )
    else:
        desktop = banner.resize((preset.width // 2, preset.height // 2), Image.Resampling.LANCZOS)
        tiles.append((f"Desktop {preset.width}x{preset.height}", desktop))
        mobile_src = banner.crop((preset.safe_left, 0, preset.safe_right, preset.height))
        mobile_w = preset.safe_width
        mobile_h = round(mobile_w * 9 / 16)
        tiles.append(
            (
                "Mobile crop 16:9",
                mobile_src.resize((mobile_w // 2, mobile_h // 2), Image.Resampling.LANCZOS),
            )
        )

    width = max(tile.width for _label_text, tile in tiles) + pad * 2
    height = pad + sum(label_h + tile.height + pad for _label_text, tile in tiles)
    sheet = Image.new("RGB", (width, height), (16, 16, 18))
    draw = ImageDraw.Draw(sheet)
    y = pad
    for text, tile in tiles:
        draw.text((pad, y + 8), text, fill=(220, 220, 220))
        y += label_h
        sheet.paste(tile, (pad, y))
        y += tile.height + pad
    return sheet


def save_jpeg(image: Image.Image, path: Path, quality: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image.convert("RGB").save(path, format="JPEG", quality=quality, optimize=True, progressive=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--preset", choices=sorted(PRESETS), default="facebook-cover")
    parser.add_argument("--fit", choices=("cover", "contain", "safe"), default=None)
    parser.add_argument("--fill", default="#000000", help="Used only with --fit contain")
    parser.add_argument("--subject-safe", action="store_true")
    parser.add_argument("--subject-padding", type=int, default=40)
    parser.add_argument("--preview", type=Path, default=None)
    parser.add_argument("--sizes-preview", type=Path, default=None)
    parser.add_argument("--quality", type=int, default=92)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.input.is_file():
        raise FileNotFoundError(f"Input not found: {args.input}")
    preset = PRESETS[args.preset]
    fill = parse_hex_color(args.fill)
    source = Image.open(args.input)
    fit = args.fit or preset.default_fit
    banner, subject, shift = fit_social_banner(
        source,
        preset=preset,
        mode=fit,
        fill=fill,
        subject_safe=args.subject_safe or fit == "safe",
        subject_padding=args.subject_padding,
    )
    save_jpeg(banner, args.output, args.quality)
    if args.preview is not None:
        save_jpeg(draw_preview(banner, preset, subject), args.preview, args.quality)
    if args.sizes_preview is not None:
        save_jpeg(draw_sizes_preview(banner, preset), args.sizes_preview, args.quality)
    print(f"wrote {args.output} {banner.size[0]}x{banner.size[1]} fit={fit}")
    if subject is not None:
        print(
            f"subject {subject.left},{subject.top}-{subject.right},{subject.bottom} crop_x={shift}"
        )
        inside = (
            subject.left >= preset.safe_left
            and subject.right <= preset.safe_right
            and subject.top >= preset.safe_top
            and subject.bottom <= preset.safe_bottom
        )
        print(f"safe_zone {inside}")
    if args.preview is not None:
        print(f"preview {args.preview}")
    if args.sizes_preview is not None:
        print(f"sizes {args.sizes_preview}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
