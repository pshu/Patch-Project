#!/usr/bin/env python3
"""Render white-on-black 5 x 7 in (landscape, 300 dpi) mission cards.

Usage:
    python3 make_cards.py missions.json [--out cards] [--only ID ...]
                          [--no-guide]

Requires: Pillow (pip install pillow)

Schema per mission: id, title, subtitle (optional), patch (optional
width_in/height_in), booster (optional: id, flight), fields (label/value).
When "booster" is present a BOOSTER field ("B1093 - Flight 6") is inserted
directly after the VEHICLE field, or first if there is no VEHICLE field.
Text is scaled down automatically (floor MIN_SCALE) if a card overflows.
"""

import argparse
import json
import re
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

DPI = 300
W, H = 7 * DPI, 5 * DPI
SAFE = int(0.30 * DPI)
BLACK, WHITE, GRAY = (0, 0, 0), (255, 255, 255), (150, 150, 150)
DEFAULT_PATCH = {"width_in": 1.9, "height_in": 2.6}
MIN_SCALE = 0.75
SCALE_STEP = 0.025

BOLD = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
]
REGULAR = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "C:/Windows/Fonts/arial.ttf",
]


def load_font(candidates, size):
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def wrap(draw, text, font, max_w):
    lines, cur = [], ""
    for word in text.split():
        trial = f"{cur} {word}".strip()
        if draw.textlength(trial, font=font) <= max_w:
            cur = trial
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines


def validate(mission, index):
    errors = []
    for key in ("id", "title", "fields"):
        if key not in mission:
            errors.append(f"missions[{index}]: missing '{key}'")
    booster = mission.get("booster")
    if booster is not None:
        if "id" not in booster or "flight" not in booster:
            errors.append(f"missions[{index}].booster: needs id and flight")
        elif not isinstance(booster["flight"], int) or booster["flight"] < 1:
            errors.append(f"missions[{index}].booster.flight: positive integer")
    for j, field in enumerate(mission.get("fields", [])):
        if "label" not in field or "value" not in field:
            errors.append(f"missions[{index}].fields[{j}]: needs label and value")
    return errors


def build_fields(mission):
    """Return the field list with the BOOSTER field inserted."""
    fields = list(mission["fields"])
    booster = mission.get("booster")
    if booster:
        entry = {"label": "BOOSTER",
                 "value": f"{booster['id']} - Flight {booster['flight']}"}
        idx = next((i + 1 for i, f in enumerate(fields)
                    if f["label"].upper() == "VEHICLE"), 0)
        fields.insert(idx, entry)
    return fields


def render(mission, show_guide, scale=1.0):
    """Return (image, overflow_px)."""
    img = Image.new("RGB", (W, H), BLACK)
    d = ImageDraw.Draw(img)

    f_title = load_font(BOLD, int(15 * scale * DPI / 72))
    f_sub = load_font(REGULAR, int(11 * scale * DPI / 72))
    f_label = load_font(BOLD, int(9 * scale * DPI / 72))
    f_value = load_font(REGULAR, int(11 * scale * DPI / 72))

    patch = {**DEFAULT_PATCH, **mission.get("patch", {})}
    pw, ph = int(patch["width_in"] * DPI), int(patch["height_in"] * DPI)
    px0, py0 = SAFE, (H - ph) // 2
    if show_guide:
        d.rectangle([px0, py0, px0 + pw, py0 + ph], outline=GRAY, width=2)

    x = px0 + pw + int(0.35 * DPI)
    max_w = W - SAFE - x
    y = SAFE

    for line in wrap(d, mission["title"], f_title, max_w):
        d.text((x, y), line, font=f_title, fill=WHITE)
        y += int(f_title.size * 1.2)
    if mission.get("subtitle"):
        d.text((x, y), mission["subtitle"], font=f_sub, fill=WHITE)
        y += int(f_sub.size * 1.5)
    d.line([(x, y), (x + max_w, y)], fill=WHITE, width=3)
    y += int(0.15 * DPI)

    for field in build_fields(mission):
        d.text((x, y), field["label"], font=f_label, fill=GRAY)
        y += int(f_label.size * 1.3)
        for line in wrap(d, field["value"], f_value, max_w):
            d.text((x, y), line, font=f_value, fill=WHITE)
            y += int(f_value.size * 1.25)
        y += int(0.10 * scale * DPI)

    return img, max(0, y - (H - SAFE))


def render_fit(mission, show_guide):
    """Render at the largest scale in [MIN_SCALE, 1.0] that fits."""
    scale = 1.0
    while True:
        img, over = render(mission, show_guide, scale)
        if over == 0 or scale - SCALE_STEP < MIN_SCALE:
            return img, over, scale
        scale = round(scale - SCALE_STEP, 3)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("data", type=Path, help="path to missions JSON")
    ap.add_argument("--out", type=Path, default=Path("cards"))
    ap.add_argument("--only", nargs="*", help="render only these mission ids")
    ap.add_argument("--no-guide", action="store_true",
                    help="omit the patch outline (use for final prints)")
    args = ap.parse_args()

    missions = json.loads(args.data.read_text(encoding="utf-8"))["missions"]

    errors = [e for i, m in enumerate(missions) for e in validate(m, i)]
    if errors:
        print("\n".join(errors), file=sys.stderr)
        sys.exit(1)

    if args.only:
        missions = [m for m in missions if m["id"] in args.only]
        if not missions:
            sys.exit("No missions matched --only")

    args.out.mkdir(parents=True, exist_ok=True)
    overflowed = []
    for m in missions:
        img, over, scale = render_fit(m, show_guide=not args.no_guide)
        name = re.sub(r"[^A-Za-z0-9_-]+", "_", m["id"])
        path = args.out / f"{name}.png"
        img.save(path, dpi=(DPI, DPI))
        note = "" if scale == 1.0 else f" (text scaled to {scale:.3f})"
        print(f"Wrote {path}{note}")
        if over:
            overflowed.append((m["id"], over))

    for mid, over in overflowed:
        print(f"WARNING: {mid} overflows the safe area by {over} px",
              file=sys.stderr)


if __name__ == "__main__":
    main()
