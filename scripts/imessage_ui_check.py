#!/usr/bin/env python3
"""Regression check for the iOS Messages renderer.

Re-renders the conversation from a real iPhone screenshot at that screenshot's
exact geometry and reports how far the pixels drift. Run it after touching any
metric in ``imessage_ui.py``.

  python scripts/imessage_ui_check.py --reference path\\to\\screenshot.png
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
from imessage_ui import ChatMessage, PhoneUI, theme_for  # noqa: E402

# The thread visible in the calibration screenshot, in order.
REFERENCE_THREAD = [
    ChatMessage("them", "then you'll be better off"),
    ChatMessage("them", "You haven't larped in a gurus dms and don't believe in the power of money"),
    ChatMessage("them", "Where's your course at"),
    ChatMessage("me", "LOL"),
    ChatMessage("me", "Nah but I've done consistent 5ks months"),
    ChatMessage("me", "For abt 4 months now"),
    ChatMessage("time", "Sat, Aug 1 at 4:57 PM"),
    ChatMessage("them", "From the daq or scale"),
    ChatMessage("time", "Sat, Aug 1 at 6:27 PM"),
    ChatMessage("me", "Scale"),
    ChatMessage("me", "I took a 2k payout from the day the other day"),
    ChatMessage("me", "and I got 2 new fundeds"),
    ChatMessage("time", "Yesterday 6:08 AM"),
    ChatMessage("them", "Why did cam start talking in the gc again like anyone other than you is working"),
    ChatMessage("me", "Sales team idk", status="Delivered"),
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", type=Path, required=True, help="iPhone screenshot to match")
    parser.add_argument("--out", type=Path, default=Path("downloads/imessage/ui_check"))
    parser.add_argument("--supersample", type=int, default=4)
    args = parser.parse_args()

    ref = Image.open(args.reference).convert("RGB")
    w, h = ref.size
    args.out.mkdir(parents=True, exist_ok=True)

    ui = PhoneUI(
        theme_for("dark"),
        "JosH!",
        "2:14",
        contact_color="2f2945",
        unread_badge=16,
        width=w * args.supersample,
        height=h * args.supersample,
    )
    mine = ui.render(REFERENCE_THREAD).resize((w, h), Image.Resampling.LANCZOS)
    mine.save(args.out / "render.png")

    side = Image.new("RGB", (w * 2 + 12, h), (255, 0, 0))
    side.paste(ref, (0, 0))
    side.paste(mine, (w + 12, 0))
    side.save(args.out / "side_by_side.png")

    rp, mp = ref.load(), mine.load()
    total = 0
    for y in range(h):
        for x in range(w):
            total += max(abs(rp[x, y][c] - mp[x, y][c]) for c in range(3))
    print(f"mean absolute pixel difference: {total / (w * h):.2f}")
    print(f"wrote {args.out / 'side_by_side.png'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
