#!/usr/bin/env python3
"""Pixel-accurate iOS Messages renderer.

Every metric in this module is expressed in "reference pixels" -- the coordinate
space of a 473x1024 iPhone screenshot (a 393x852pt device captured at 3x and
scaled down). ``sc()`` converts those into output pixels, so the layout stays a
1:1 replica of iOS at any canvas size.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ASSETS_DIR = Path(__file__).resolve().parent / "assets" / "imessage"
FONTS_DIR = ASSETS_DIR / "fonts"

WIDTH = 1080
HEIGHT = 1920

REF_W = 473.0  # width of the reference screenshot this layout was measured from
REF_H = 1024.0
SS = 4  # supersampling factor for vector shapes


def sc(value: float, width: int = WIDTH) -> float:
    """Reference pixels -> output pixels."""
    return value * width / REF_W


# --- message column (reference px) ---------------------------------------
M_SIDE = 20.0  # bubble inset from the screen edge
M_MAX_BUBBLE = 325.0  # widest a bubble ever gets
M_RADIUS = 23.0  # bubble corner radius, capped at half the height
M_PAD_X = 16.3  # horizontal text inset inside a bubble
M_PAD_Y = 11.9  # vertical text inset inside a bubble
M_LINE_H = 24.4  # 17pt SF Pro Text default leading
M_FONT = 20.4  # 17pt
M_TAIL_H = 7.5  # how far the tail hangs below the bubble body
M_TAIL_MEET = 23.0  # where the tail rejoins the bottom edge, from the outer edge
M_TAIL_TIP_X = 10.5  # tail tip, measured in from the outer edge
M_TAIL_OUT = 12.0  # tail's outer edge where it leaves the corner arc
M_TAIL_LIFT = 5.0  # how far up the corner arc the tail starts
M_GAP = 5.9  # vertical gap between consecutive bubbles

M_TS_FONT = 14.4  # 12pt date separator
M_TS_ABOVE = 9.0
M_TS_BELOW = 5.0
M_STATUS_FONT = 13.2  # 11pt "Delivered"
M_STATUS_BLOCK = 17.2  # vertical slot the label occupies below the bubble
M_STATUS_ABOVE = 1.0
M_STATUS_RIGHT = 46.0  # "Delivered" right edge, inset from the screen edge

M_TYPING_W = 72.0
M_TYPING_H = 41.0

# --- navigation chrome (reference px) ------------------------------------
N_STATUS_CY = 31.0  # status bar text centre line
N_STATUS_FONT = 20.6  # 17pt semibold
N_CLOCK_CX = 77.0
N_ICONS_RIGHT = 441.0
N_TOP = 57.0  # top of the floating nav controls
N_BTN = 52.0  # back pill / FaceTime button height
N_BACK_W = 92.0
N_AVATAR = 72.0
N_AVATAR_TOP = 57.0
N_NAME_H = 36.0
N_NAME_TOP = 126.0
N_NAME_FONT = 20.4  # 17pt semibold
N_INITIALS_FONT = 38.5
N_SCRIM_BOTTOM = 195.0  # blur under the nav fades out here
N_SCRIM_SIGMA = 10.0  # blur sigma at the very top

# --- composer (reference px) ---------------------------------------------
C_BOTTOM_GAP = 35.0  # composer bottom edge to the screen bottom
C_H = 49.0
C_PLUS_X = 34.0
C_FIELD_X0 = 97.0
C_FIELD_X1 = 438.0
C_TEXT_X = 116.0
C_FONT = 20.4
C_MIC_RIGHT = 419.0

M_SCROLLBAR_W = 4.0
M_SCROLLBAR_RIGHT = 470.0
M_SCROLLBAR_TRACK_TOP = 160.0
M_SCROLLBAR_BELOW = 7.0
M_SCROLLBAR_COVERAGE = 0.20  # thumb length as a fraction of the track


PX_PER_PT = REF_H / 852.0  # reference px per iOS point

# Apple ships SF Pro with an optical tracking table; without it text runs a few
# percent wide and wraps in the wrong places. Values are points per character.
_TRACKING_PT = {
    6: 0.24, 8: 0.21, 9: 0.19, 10: 0.12, 11: 0.06, 12: 0.0, 13: -0.08, 14: -0.15,
    15: -0.23, 16: -0.31, 17: -0.43, 18: -0.44, 20: -0.45, 22: -0.26, 24: -0.23,
    28: -0.17, 32: -0.13, 36: -0.07, 40: -0.03, 44: 0.01,
}


def tracking_for(size_ref_px: float) -> float:
    """Tracking in reference pixels for a font drawn at ``size_ref_px``."""
    pt = size_ref_px / PX_PER_PT
    keys = sorted(_TRACKING_PT)
    if pt <= keys[0]:
        value = _TRACKING_PT[keys[0]]
    elif pt >= keys[-1]:
        value = _TRACKING_PT[keys[-1]]
    else:
        hi = next(k for k in keys if k >= pt)
        lo = max(k for k in keys if k <= pt)
        value = _TRACKING_PT[lo] if hi == lo else (
            _TRACKING_PT[lo] + (_TRACKING_PT[hi] - _TRACKING_PT[lo]) * (pt - lo) / (hi - lo)
        )
    return value * PX_PER_PT


@dataclass(frozen=True)
class Theme:
    name: str
    bg: tuple[int, int, int]
    incoming: tuple[int, int, int]
    outgoing: tuple[int, int, int]
    incoming_text: tuple[int, int, int]
    outgoing_text: tuple[int, int, int]
    secondary: tuple[int, int, int]
    placeholder: tuple[int, int, int]
    field_bg: tuple[int, int, int]
    scrollbar: tuple[int, int, int]
    glass_tint: int  # flat term added on top of the blurred backdrop
    glass_gain: float  # how much of the backdrop survives behind the glass
    status_ink: tuple[int, int, int]
    status_dim: tuple[int, int, int]
    battery: tuple[int, int, int]
    ink: tuple[int, int, int]
    white: tuple[int, int, int] = (255, 255, 255)
    black: tuple[int, int, int] = (0, 0, 0)


DARK = Theme(
    name="dark",
    bg=(0, 0, 0),
    incoming=(38, 38, 40),
    outgoing=(28, 149, 254),
    incoming_text=(255, 255, 255),
    outgoing_text=(255, 255, 255),
    secondary=(142, 142, 147),
    placeholder=(122, 122, 124),
    field_bg=(24, 24, 24),
    scrollbar=(128, 128, 128),
    glass_tint=26,
    glass_gain=0.45,
    status_ink=(255, 255, 255),
    status_dim=(72, 72, 74),
    battery=(255, 214, 10),
    ink=(255, 255, 255),
)

LIGHT = Theme(
    name="light",
    bg=(255, 255, 255),
    incoming=(233, 233, 235),
    outgoing=(24, 143, 255),
    incoming_text=(0, 0, 0),
    outgoing_text=(255, 255, 255),
    secondary=(142, 142, 147),
    placeholder=(142, 142, 147),
    field_bg=(242, 242, 247),
    scrollbar=(180, 180, 184),
    glass_tint=194,
    glass_gain=0.16,
    status_ink=(0, 0, 0),
    status_dim=(197, 197, 200),
    battery=(255, 204, 0),
    ink=(0, 0, 0),
)


def theme_for(name: str) -> Theme:
    return LIGHT if str(name).lower() == "light" else DARK


@dataclass
class ChatMessage:
    sender: str  # "me" | "them" | "time"
    text: str
    status: str = ""


@lru_cache(maxsize=64)
def _font(size_px: int, weight: str = "regular", display: bool = False) -> ImageFont.FreeTypeFont:
    family = "Display" if display else "Text"
    name = {"regular": "Regular", "medium": "Medium", "semibold": "Semibold", "bold": "Bold"}[weight]
    path = FONTS_DIR / f"SF-Pro-{family}-{name}.otf"
    if path.is_file():
        return ImageFont.truetype(str(path), size_px)
    fallback = FONTS_DIR / f"Inter-{'SemiBold' if name == 'Semibold' else name}.ttf"
    if fallback.is_file():
        return ImageFont.truetype(str(fallback), size_px)
    return ImageFont.load_default()


def _initials(name: str) -> str:
    parts = [p for p in name.replace("_", " ").split() if p]
    if not parts:
        return "?"
    if len(parts) == 1:
        return parts[0][0].upper()
    return (parts[0][0] + parts[-1][0]).upper()


def _avatar_colors(name: str) -> tuple[tuple[int, int, int], tuple[int, int, int]]:
    """Top and bottom stops of the iOS monogram gradient."""
    palette = [
        ((86, 81, 101), (47, 41, 69)),
        ((92, 84, 78), (56, 48, 42)),
        ((72, 84, 96), (40, 50, 62)),
        ((96, 78, 86), (58, 42, 50)),
        ((78, 92, 80), (44, 56, 46)),
        ((84, 78, 96), (48, 42, 62)),
    ]
    digest = hashlib.md5(name.encode("utf-8")).hexdigest()
    return palette[int(digest[:2], 16) % len(palette)]


def _bezier(p0, p1, p2, p3, steps: int = 24) -> list[tuple[float, float]]:
    out = []
    for i in range(steps + 1):
        t = i / steps
        u = 1 - t
        out.append(
            (
                u * u * u * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t * t * t * p3[0],
                u * u * u * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t * t * t * p3[1],
            )
        )
    return out


class TextStyle:
    """A font plus the per-character tracking iOS applies at that size."""

    def __init__(self, font: ImageFont.FreeTypeFont, tracking: float):
        self.font = font
        self.tracking = tracking
        self.ascent, self.descent = font.getmetrics()

    def width(self, draw: ImageDraw.ImageDraw, text: str) -> float:
        if not text:
            return 0.0
        return draw.textlength(text, font=self.font) + self.tracking * (len(text) - 1)

    def draw(self, draw: ImageDraw.ImageDraw, xy, text: str, fill, anchor: str = "ls") -> None:
        if not text:
            return
        x, y = xy
        horizontal, vertical = anchor[0], anchor[1]
        total = self.width(draw, text)
        if horizontal == "m":
            x -= total / 2
        elif horizontal == "r":
            x -= total
        if abs(self.tracking) < 1e-6:
            draw.text((x, y), text, font=self.font, fill=fill, anchor="l" + vertical)
            return
        for i, ch in enumerate(text):
            if ch != " ":
                offset = draw.textlength(text[:i], font=self.font) + self.tracking * i
                draw.text((x + offset, y), ch, font=self.font, fill=fill, anchor="l" + vertical)


def _wrap(draw: ImageDraw.ImageDraw, text: str, style: TextStyle, max_width: float) -> list[str]:
    lines: list[str] = []
    for paragraph in text.split("\n"):
        words = paragraph.split()
        if not words:
            lines.append("")
            continue
        current = ""
        for word in words:
            trial = word if not current else f"{current} {word}"
            if style.width(draw, trial) <= max_width:
                current = trial
                continue
            if current:
                lines.append(current)
            if style.width(draw, word) <= max_width:
                current = word
                continue
            chunk = ""
            for ch in word:
                if style.width(draw, chunk + ch) <= max_width:
                    chunk += ch
                else:
                    if chunk:
                        lines.append(chunk)
                    chunk = ch
            current = chunk
        lines.append(current)
    return lines or [""]


class PhoneUI:
    """Draws a single frame of an iOS Messages conversation."""

    def __init__(
        self,
        theme: Theme,
        contact_name: str,
        clock: str,
        contact_color: str | None = None,
        unread_badge: int | None = None,
        *,
        width: int = WIDTH,
        height: int = HEIGHT,
        show_home_indicator: bool = False,
    ):
        self.theme = theme
        self.contact_name = contact_name
        self.clock = clock
        self.unread_badge = 16 if unread_badge in (None, "") else int(unread_badge)
        self.width = width
        self.height = height
        self.show_home_indicator = show_home_indicator
        self.s = width / REF_W

        top, bottom = _avatar_colors(contact_name)
        override = self._parse_color(contact_color)
        if override:
            top = tuple(min(255, int(c * 1.35) + 24) for c in override)
            bottom = override
        self.avatar_top, self.avatar_bottom = top, bottom

        self.f_bubble = self._style(M_FONT, "regular")
        self.f_ts_bold = self._style(M_TS_FONT, "semibold")
        self.f_ts = self._style(M_TS_FONT, "regular")
        self.f_status = self._style(M_STATUS_FONT, "regular")
        self.f_clock = self._style(N_STATUS_FONT, "semibold")
        self.f_name = self._style(N_NAME_FONT, "semibold")
        self.f_badge = self._style(15.5, "semibold")
        self.f_initials = self._style(N_INITIALS_FONT, "medium", display=True)
        self.f_composer = self._style(C_FONT, "regular")

        self.composer_top = self.height - self._px(C_BOTTOM_GAP + C_H)
        self.message_bottom = self.composer_top - self._px(19.0)

    # -- helpers ----------------------------------------------------------
    def _style(self, size_ref: float, weight: str, display: bool = False) -> TextStyle:
        return TextStyle(_font(self._px(size_ref), weight, display), tracking_for(size_ref) * self.s)

    def _px(self, ref: float) -> int:
        return max(1, int(round(ref * self.s)))

    def _f(self, ref: float) -> float:
        return ref * self.s

    @staticmethod
    def _parse_color(value: str | None) -> tuple[int, int, int] | None:
        if not value:
            return None
        raw = str(value).strip().lstrip("#")
        if len(raw) != 6:
            return None
        try:
            return int(raw[0:2], 16), int(raw[2:4], 16), int(raw[4:6], 16)
        except ValueError:
            return None

    def _mask(self, size: tuple[int, int], paint) -> Image.Image:
        """Render a shape at SSx and downsample it into an antialiased mask."""
        big = Image.new("L", (size[0] * SS, size[1] * SS), 0)
        paint(ImageDraw.Draw(big), SS)
        return big.resize(size, Image.Resampling.LANCZOS)

    def _stamp(self, img: Image.Image, mask: Image.Image, xy: tuple[int, int], color) -> None:
        patch = Image.new("RGB", mask.size, color)
        img.paste(patch, (int(xy[0]), int(xy[1])), mask)

    # -- bubbles ----------------------------------------------------------
    def _bubble_mask(self, w: int, h: int, tail: str | None) -> Image.Image:
        key = (w, h, tail)
        cache = getattr(self, "_bubble_cache", None)
        if cache is None:
            cache = self._bubble_cache = {}
        if key in cache:
            return cache[key]

        tail_h = self._f(M_TAIL_H) if tail else 0.0
        total_h = int(round(h + tail_h))
        radius = min(self._f(M_RADIUS), h / 2)

        def paint(d: ImageDraw.ImageDraw, s: int) -> None:
            d.rounded_rectangle((0, 0, w * s - 1, h * s - 1), radius=radius * s, fill=255)
            if not tail:
                return
            unit = self.s * s  # reference px -> supersampled px
            th = tail_h * s
            bottom = h * s
            if tail == "them":
                outer, sign = 0.0, 1.0
            else:
                outer, sign = w * s - 1, -1.0

            def p(inset: float, dy: float) -> tuple[float, float]:
                return outer + sign * inset * unit, bottom + dy * unit

            # The tail leaves the corner arc, hooks out and down to a tip, then
            # sweeps back up into the bottom edge.
            start = p(M_TAIL_OUT, -M_TAIL_LIFT)
            tip = p(M_TAIL_TIP_X, M_TAIL_H)
            pts = _bezier(
                start,
                p(M_TAIL_OUT - 0.6, M_TAIL_H * 0.32),
                p(M_TAIL_TIP_X - 0.4, M_TAIL_H * 0.70),
                tip,
            )
            pts += _bezier(
                tip,
                p(M_TAIL_TIP_X + 4.5, M_TAIL_H * 0.86),
                p(M_TAIL_MEET - 4.5, M_TAIL_H * 0.36),
                p(M_TAIL_MEET, 0.0),
            )
            d.polygon(pts, fill=255)

        mask = self._mask((w, total_h), paint)
        cache[key] = mask
        return mask

    def _bubble_size(self, draw: ImageDraw.ImageDraw, message: ChatMessage) -> tuple[int, int, list[str]]:
        max_text = self._f(M_MAX_BUBBLE - 2 * M_PAD_X)
        lines = _wrap(draw, message.text, self.f_bubble, max_text)
        text_w = max((self.f_bubble.width(draw, line) for line in lines), default=0)
        w = int(round(text_w + 2 * self._f(M_PAD_X)))
        h = int(round(len(lines) * self._f(M_LINE_H) + 2 * self._f(M_PAD_Y)))
        return min(w, int(round(self._f(M_MAX_BUBBLE)))), h, lines

    def _draw_bubble(
        self,
        img: Image.Image,
        draw: ImageDraw.ImageDraw,
        message: ChatMessage,
        x: int,
        y: int,
        w: int,
        h: int,
        lines: list[str],
        tail: bool,
    ) -> None:
        t = self.theme
        incoming = message.sender == "them"
        fill = t.incoming if incoming else t.outgoing
        mask = self._bubble_mask(w, h, message.sender if tail else None)
        self._stamp(img, mask, (x, y), fill)

        ink = t.incoming_text if incoming else t.outgoing_text
        style = self.f_bubble
        line_h = self._f(M_LINE_H)
        top = y + self._f(M_PAD_Y) + (line_h - (style.ascent + style.descent)) / 2 + style.ascent
        for i, line in enumerate(lines):
            style.draw(draw, (x + self._f(M_PAD_X), top + i * line_h), line, ink)

    def _draw_timestamp(self, draw: ImageDraw.ImageDraw, message: ChatMessage, y: float) -> None:
        """iOS renders the date portion semibold and the time portion regular."""
        text = message.text
        head, tail = text, ""
        for sep in (" at ", ", "):
            if sep in text:
                idx = text.index(sep) + len(sep)
                head, tail = text[:idx], text[idx:]
                break
        else:
            parts = text.rsplit(" ", 2)
            if len(parts) == 3:
                head, tail = parts[0] + " ", parts[1] + " " + parts[2]
        w_head = self.f_ts_bold.width(draw, head)
        w_tail = self.f_ts.width(draw, tail)
        x = (self.width - (w_head + w_tail)) / 2
        base = y + self.f_ts_bold.ascent
        self.f_ts_bold.draw(draw, (x, base), head, self.theme.secondary)
        self.f_ts.draw(draw, (x + w_head, base), tail, self.theme.secondary)

    def _draw_typing(self, img: Image.Image, draw: ImageDraw.ImageDraw, y: float, phase: int) -> None:
        t = self.theme
        w, h = self._px(M_TYPING_W), self._px(M_TYPING_H)
        x = self._px(M_SIDE)
        self._stamp(img, self._bubble_mask(w, h, "them"), (x, int(y)), t.incoming)
        cy = y + h / 2
        gap = self._f(13.0)
        r = self._f(4.4)
        cx = x + w / 2 - gap
        for i in range(3):
            lift = 1 if (phase % 3) == i else 0
            rr = r + lift * self._f(0.8)
            yy = cy - lift * self._f(2.6)
            colour = (190, 190, 194) if lift else (122, 122, 126)
            draw.ellipse((cx + i * gap - rr, yy - rr, cx + i * gap + rr, yy + rr), fill=colour)

    # -- message column ---------------------------------------------------
    def _layout(self, draw: ImageDraw.ImageDraw, messages: list[ChatMessage], typing: str | None):
        """Lay messages out from the bottom up; returns drawable items."""
        blocks = []
        for m in messages:
            if m.sender == "time":
                blocks.append((m, 0, 0, []))
            else:
                w, h, lines = self._bubble_size(draw, m)
                blocks.append((m, w, h, lines))

        content_h = sum(
            (self._f(M_TS_FONT + M_TS_ABOVE + M_TS_BELOW) if m.sender == "time" else h + self._f(M_GAP + M_TAIL_H))
            for m, _, h, _ in blocks
        )

        items = []
        cursor = self.message_bottom
        below_sender = typing or ""
        receipt_index = None
        for index, (message, _, _, _) in enumerate(blocks):
            if message.sender in {"me", "them"}:
                receipt_index = index
        if receipt_index is not None and blocks[receipt_index][0].sender != "me":
            receipt_index = None
        if typing == "them":
            cursor -= self._px(M_TYPING_H) + self._f(M_TAIL_H)
            items.append(("typing", cursor))
            cursor -= self._f(M_GAP)

        for index in range(len(blocks) - 1, -1, -1):
            message, w, h, lines = blocks[index]
            if message.sender == "time":
                cursor -= self._f(M_TS_BELOW)
                ts_h = self._f(M_TS_FONT)
                cursor -= ts_h
                items.append(("time", message, cursor))
                cursor -= self._f(M_TS_ABOVE)
                below_sender = ""
                continue

            tail = message.sender != below_sender
            # iOS keeps Delivered/Read under the latest outgoing bubble only.
            if message.status and index == receipt_index:
                cursor -= self._f(M_STATUS_BLOCK)
                items.append(("status", message.status, cursor))
                cursor -= self._f(M_STATUS_ABOVE)
            if tail:
                cursor -= self._f(M_TAIL_H)
            cursor -= h
            x = self._px(M_SIDE) if message.sender == "them" else int(round(self.width - self._f(M_SIDE) - w))
            items.append(("bubble", message, x, int(round(cursor)), w, h, lines, tail))
            cursor -= self._f(M_GAP)
            below_sender = message.sender
            if cursor < -self._f(120):
                break
        return items, content_h

    def _draw_messages(self, img: Image.Image, items) -> None:
        draw = ImageDraw.Draw(img)
        for item in reversed(items):
            kind = item[0]
            if kind == "bubble":
                _, message, x, y, w, h, lines, tail = item
                if y > self.height:
                    continue
                self._draw_bubble(img, draw, message, x, y, w, h, lines, tail)
            elif kind == "time":
                self._draw_timestamp(draw, item[1], item[2])
            elif kind == "status":
                self.f_status.draw(
                    draw,
                    (self.width - self._f(M_STATUS_RIGHT), item[2] + self.f_status.ascent),
                    item[1],
                    self.theme.secondary,
                    anchor="rs",
                )
            elif kind == "typing":
                self._draw_typing(img, draw, item[1], self._typing_phase)

    def _draw_scrollbar(self, img: Image.Image, coverage: float) -> None:
        """Thumb pinned to the bottom: the thread is always scrolled to the newest message."""
        w = self._px(M_SCROLLBAR_W)
        x = int(round(self.width - self._f(REF_W - M_SCROLLBAR_RIGHT) - w))
        track_top = self._f(M_SCROLLBAR_TRACK_TOP)
        bottom = self.message_bottom + self._f(M_SCROLLBAR_BELOW)
        track = bottom - track_top
        if track < w * 4:
            return
        h = int(round(track * max(0.08, min(0.8, coverage))))
        mask = self._mask((w, h), lambda d, s: d.rounded_rectangle((0, 0, w * s - 1, h * s - 1), radius=w * s / 2, fill=255))
        self._stamp(img, mask, (x, int(round(bottom - h))), self.theme.scrollbar)

    # -- nav chrome -------------------------------------------------------
    def _apply_scrim(self, img: Image.Image) -> None:
        """Progressive blur so message content dissolves under the floating nav.

        Each row is a blend of two neighbouring blur levels, which keeps the
        ramp smooth instead of compounding blur on blur.
        """
        cutoff = int(round(self._f(N_SCRIM_BOTTOM)))
        if cutoff <= 0:
            return
        base = img.crop((0, 0, self.width, cutoff))
        sigma_max = self._f(N_SCRIM_SIGMA)
        levels = [base] + [base.filter(ImageFilter.GaussianBlur(sigma_max * f)) for f in (0.25, 0.5, 0.75, 1.0)]
        out = base.copy()
        for i in range(1, len(levels)):
            mask = Image.new("L", (self.width, cutoff), 0)
            md = ImageDraw.Draw(mask)
            for y in range(cutoff):
                # 1 at the very top, 0 at the cutoff, eased so the fade is gentle
                strength = (1.0 - y / cutoff) ** 1.6 * (len(levels) - 1)
                weight = max(0.0, min(1.0, strength - (i - 1)))
                md.line((0, y, self.width, y), fill=int(255 * weight))
            out = Image.composite(levels[i], out, mask)
        img.paste(out, (0, 0))

    def _glass(self, img: Image.Image, box: tuple[int, int, int, int], mask: Image.Image) -> None:
        """iOS 26 liquid-glass: blurred backdrop, lifted toward the tint colour."""
        t = self.theme
        x0, y0, x1, y1 = box
        pad = self._px(14)
        cx0, cy0 = max(0, x0 - pad), max(0, y0 - pad)
        cx1, cy1 = min(self.width, x1 + pad), min(self.height, y1 + pad)
        patch = img.crop((cx0, cy0, cx1, cy1)).filter(ImageFilter.GaussianBlur(self._f(6)))
        patch = patch.point(lambda v: min(255, int(v * t.glass_gain + t.glass_tint)))
        plate = patch.crop((x0 - cx0, y0 - cy0, x0 - cx0 + (x1 - x0), y0 - cy0 + (y1 - y0)))
        img.paste(plate, (x0, y0), mask)

    def _capsule_mask(self, w: int, h: int) -> Image.Image:
        return self._mask((w, h), lambda d, s: d.rounded_rectangle((0, 0, w * s - 1, h * s - 1), radius=min(w, h) * s / 2, fill=255))

    def _chevron(
        self,
        draw: ImageDraw.ImageDraw,
        vertex_x: float,
        cy: float,
        half_h: float,
        depth: float,
        width: float,
        fill,
        *,
        left: bool,
    ) -> None:
        sign = 1 if left else -1
        pts = [
            (vertex_x + sign * depth, cy - half_h),
            (vertex_x, cy),
            (vertex_x + sign * depth, cy + half_h),
        ]
        draw.line(pts, fill=fill, width=int(round(width)), joint="curve")
        r = width / 2
        for x, y in pts:
            draw.ellipse((x - r, y - r, x + r, y + r), fill=fill)

    def _draw_status_bar(self, img: Image.Image) -> None:
        t = self.theme
        draw = ImageDraw.Draw(img)
        self.f_clock.draw(draw, (self._f(N_CLOCK_CX), self._f(N_STATUS_CY)), self.clock, t.status_ink, anchor="mm")

        box_w, box_h = 96.0, 19.0  # reference px
        left = self._f(N_ICONS_RIGHT - box_w)
        top = self._f(22.0)
        w, h = int(round(self._f(box_w))), int(round(self._f(box_h)))

        def sprite(paint) -> Image.Image:
            return self._mask((w, h), lambda d, k: paint(d, self.s * k))

        def bars(indices):
            def paint(d, u):
                base = 16.5 * u
                for i in indices:
                    bh = (6.0, 8.0, 12.0, 15.0)[i]
                    bx = (0.0, 6.7, 13.3, 20.0)[i] * u
                    d.rounded_rectangle((bx, base - bh * u, bx + 3.6 * u, base), radius=1.2 * u, fill=255)
                if 0 in indices:  # wifi rides along with the "live" white ink
                    wx, wy = 42.0 * u, 17.0 * u
                    for r in (15.5, 10.5, 5.5):
                        d.arc(
                            (wx - r * u, wy - r * u, wx + r * u, wy + r * u),
                            216, 324, fill=255, width=int(round(2.7 * u)),
                        )
                    d.ellipse((wx - 2.0 * u, wy - 3.4 * u, wx + 2.0 * u, wy + 0.6 * u), fill=255)
            return paint

        self._stamp(img, sprite(bars([0])), (int(round(left)), int(round(top))), t.status_ink)
        self._stamp(img, sprite(bars([1, 2, 3])), (int(round(left)), int(round(top))), t.status_dim)

        def battery_outline(d, u):
            d.rounded_rectangle((62 * u, 1 * u, 91 * u, 17 * u), radius=4.6 * u, outline=255, width=int(round(1.7 * u)))
            d.rounded_rectangle((92.6 * u, 7 * u, 94.6 * u, 11 * u), radius=1.0 * u, fill=255)

        def battery_fill(d, u):
            d.rounded_rectangle((64.5 * u, 3.4 * u, 73.5 * u, 14.6 * u), radius=2.6 * u, fill=255)

        self._stamp(img, sprite(battery_outline), (int(round(left)), int(round(top))), (108, 108, 110))
        self._stamp(img, sprite(battery_fill), (int(round(left)), int(round(top))), t.battery)

    def _draw_nav(self, img: Image.Image) -> None:
        t = self.theme
        top = int(round(self._f(N_TOP)))
        btn = self._px(N_BTN)

        # back pill
        bw = self._px(N_BACK_W)
        bx = int(round(self._f(M_SIDE)))
        mask = self._capsule_mask(bw, btn)
        self._glass(img, (bx, top, bx + bw, top + btn), mask)
        draw = ImageDraw.Draw(img)
        cy = top + btn / 2
        self._chevron(draw, bx + self._f(17.5), cy, self._f(10.5), self._f(9.0), self._f(4.0), t.ink, left=True)

        label = "99+" if self.unread_badge > 99 else str(self.unread_badge)
        pad = self._f(6.5)
        tw = self.f_badge.width(draw, label)
        badge_w = int(round(max(self._f(22.0), tw + 2 * pad)))
        badge_h = self._px(22.0)
        badge_x = int(round(bx + self._f(42.0)))
        badge_y = int(round(cy - badge_h / 2))
        self._stamp(img, self._capsule_mask(badge_w, badge_h), (badge_x, badge_y), (249, 249, 249))
        self.f_badge.draw(draw, (badge_x + badge_w / 2, badge_y + badge_h / 2), label, (20, 20, 22), anchor="mm")

        # FaceTime button
        fx = int(round(self.width - self._f(M_SIDE) - btn))
        mask = self._capsule_mask(btn, btn)
        self._glass(img, (fx, top, fx + btn, top + btn), mask)
        draw = ImageDraw.Draw(img)
        self._draw_facetime_icon(img, fx + btn / 2, cy)

        # avatar
        d = self._px(N_AVATAR)
        ax = int(round((self.width - d) / 2))
        ay = int(round(self._f(N_AVATAR_TOP)))
        self._draw_avatar(img, ax, ay, d)

        # name pill
        draw = ImageDraw.Draw(img)
        name = self.contact_name
        nw = self.f_name.width(draw, name)
        chev = self._f(13.0)
        pill_w = int(round(nw + chev + self._f(30.0)))
        pill_h = self._px(N_NAME_H)
        px0 = int(round((self.width - pill_w) / 2))
        py0 = int(round(self._f(N_NAME_TOP)))
        self._glass(img, (px0, py0, px0 + pill_w, py0 + pill_h), self._capsule_mask(pill_w, pill_h))
        draw = ImageDraw.Draw(img)
        self.f_name.draw(draw, (px0 + self._f(15.0), py0 + pill_h / 2), name, t.ink, anchor="lm")
        self._chevron(
            draw,
            px0 + self._f(15.0) + nw + chev * 0.85,
            py0 + pill_h / 2,
            self._f(6.5),
            self._f(4.0),
            self._f(2.6),
            t.secondary,
            left=False,
        )

    def _draw_facetime_icon(self, img: Image.Image, cx: float, cy: float) -> None:
        w = int(round(self._f(32)))
        h = int(round(self._f(23)))

        def paint(d: ImageDraw.ImageDraw, k: int) -> None:
            u = self.s * k
            lw = 2.4 * u
            d.rounded_rectangle(
                (lw / 2, lw / 2, 22.5 * u - lw / 2, 22.6 * u - lw / 2),
                radius=6.4 * u,
                outline=255,
                width=int(round(lw)),
            )
            pts = [(22.0 * u, 8.0 * u), (30.8 * u, 2.6 * u), (30.8 * u, 20.0 * u), (22.0 * u, 14.6 * u)]
            d.line(pts + [pts[0]], fill=255, width=int(round(lw)), joint="curve")

        mask = self._mask((w, h), paint)
        self._stamp(img, mask, (int(round(cx - w / 2)), int(round(cy - h / 2))), self.theme.ink)

    def _draw_avatar(self, img: Image.Image, x: int, y: int, d: int) -> None:
        grad = Image.new("RGB", (1, d))
        gp = grad.load()
        for i in range(d):
            f = i / max(1, d - 1)
            gp[0, i] = tuple(int(self.avatar_top[c] * (1 - f) + self.avatar_bottom[c] * f) for c in range(3))
        grad = grad.resize((d, d))
        mask = self._mask((d, d), lambda dr, s: dr.ellipse((0, 0, d * s - 1, d * s - 1), fill=255))
        img.paste(grad, (x, y), mask)
        draw = ImageDraw.Draw(img)
        self.f_initials.draw(draw, (x + d / 2, y + d * 0.5), _initials(self.contact_name), (255, 255, 255), anchor="mm")

    # -- composer ---------------------------------------------------------
    def _draw_composer(self, img: Image.Image, composer: str) -> None:
        t = self.theme
        h = self._px(C_H)
        y = int(round(self.composer_top))
        plus_x = int(round(self._f(C_PLUS_X)))
        field_x0 = int(round(self._f(C_FIELD_X0)))
        field_x1 = int(round(self._f(C_FIELD_X1)))

        self._stamp(img, self._capsule_mask(h, h), (plus_x, y), t.field_bg)
        field_w = field_x1 - field_x0
        self._stamp(img, self._capsule_mask(field_w, h), (field_x0, y), t.field_bg)

        draw = ImageDraw.Draw(img)
        cx, cy = plus_x + h / 2, y + h / 2
        arm = self._f(9.0)
        lw = self._f(2.6)
        draw.line((cx - arm, cy, cx + arm, cy), fill=t.ink, width=int(round(lw)))
        draw.line((cx, cy - arm, cx, cy + arm), fill=t.ink, width=int(round(lw)))

        if composer:
            text = composer
            limit = field_w - self._f(58)
            while self.f_composer.width(draw, text) > limit and len(text) > 1:
                text = text[1:]
            self.f_composer.draw(draw, (self._f(C_TEXT_X), cy), text, t.ink, anchor="lm")
            self._draw_send_button(img, field_x1 - self._f(4) - h * 0.78, y + (h - h * 0.78) / 2, h * 0.78)
        else:
            self.f_composer.draw(draw, (self._f(C_TEXT_X), cy), "iMessage", t.placeholder, anchor="lm")
            self._draw_mic(img, self._f(C_MIC_RIGHT), cy)

        if self.show_home_indicator:
            bar_w, bar_h = self._px(139), self._px(5)
            self._stamp(
                img,
                self._capsule_mask(bar_w, bar_h),
                ((self.width - bar_w) // 2, int(self.height - self._f(10) - bar_h)),
                (70, 70, 72),
            )

    def _draw_mic(self, img: Image.Image, right: float, cy: float) -> None:
        w = int(round(self._f(13)))
        h = int(round(self._f(20)))

        def paint(d: ImageDraw.ImageDraw, k: int) -> None:
            u = self.s * k
            lw = 1.6 * u
            d.rounded_rectangle((4.2 * u, 0.4 * u, 8.8 * u, 11.6 * u), radius=2.3 * u, fill=255)
            d.arc((0.3 * u, 4.2 * u, 12.7 * u, 16.6 * u), 0, 180, fill=255, width=int(round(lw)))
            d.line((6.5 * u, 15.6 * u, 6.5 * u, 19.6 * u), fill=255, width=int(round(lw)))

        mask = self._mask((w, h), paint)
        self._stamp(img, mask, (int(round(right - w)), int(round(cy - h / 2))), self.theme.placeholder)

    def _draw_send_button(self, img: Image.Image, x: float, y: float, d: float) -> None:
        size = int(round(d))

        def paint(dr: ImageDraw.ImageDraw, k: int) -> None:
            u = self.s * k
            dr.ellipse((0, 0, size * k - 1, size * k - 1), fill=255)

        mask = self._mask((size, size), paint)
        self._stamp(img, mask, (int(round(x)), int(round(y))), self.theme.outgoing)
        draw = ImageDraw.Draw(img)
        cx, cy = x + d / 2, y + d / 2
        arm = d * 0.26
        lw = self._f(3.0)
        draw.line((cx, cy + arm, cx, cy - arm), fill=(255, 255, 255), width=int(round(lw)))
        draw.line((cx, cy - arm, cx - arm * 0.72, cy - arm * 0.28), fill=(255, 255, 255), width=int(round(lw)))
        draw.line((cx, cy - arm, cx + arm * 0.72, cy - arm * 0.28), fill=(255, 255, 255), width=int(round(lw)))

    # -- entry point ------------------------------------------------------
    def render(
        self,
        messages: list[ChatMessage],
        *,
        typing: str | None = None,
        composer: str = "",
        phase: int = 0,
    ) -> Image.Image:
        self._typing_phase = phase
        img = Image.new("RGB", (self.width, self.height), self.theme.bg)
        probe = ImageDraw.Draw(img)
        items, content_h = self._layout(probe, messages, typing)
        self._draw_messages(img, items)
        self._draw_scrollbar(img, min(M_SCROLLBAR_COVERAGE, self.message_bottom / max(1.0, content_h)))
        self._apply_scrim(img)
        self._draw_status_bar(img)
        self._draw_nav(img)
        self._draw_composer(img, composer)
        return img
