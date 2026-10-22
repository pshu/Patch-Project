#!/usr/bin/env python3
"""Render white-on-black (or, with --white, black-on-white) 5 x 7 in
(landscape, 300 dpi) mission cards.

Usage:
    python3 make_cards.py missions.json [--out cards] [--only ID ...]
                          [--no-guide] [--white]

Requires: Pillow (pip install pillow)

Schema per mission: id, title, subtitle (optional), patch (optional
width_in/height_in, shape: rect/round/diamond), booster (optional: id, flight), fields (label/value).
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
BG, FG, GRAY = (0, 0, 0), (255, 255, 255), (150, 150, 150)  # background, text, labels/guide
WHITE_COLORS = (255, 255, 255), (0, 0, 0), (110, 110, 110)  # --white
SHAPES = ("rect", "round", "diamond")
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
    shape = mission.get("patch", {}).get("shape", "rect")
    if shape not in SHAPES:
        errors.append(f"missions[{index}].patch.shape: one of {', '.join(SHAPES)}")
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


def render(mission, show_guide, scale=1.0, mode="land"):
    """Return (image, overflow_px). Overflow counts vertical and horizontal."""
    portrait = mode == "portrait"
    stack = mode == "stack"
    cw, ch = (H, W) if portrait else (W, H)
    img = Image.new("RGB", (cw, ch), BG)
    d = ImageDraw.Draw(img)

    f_title = load_font(BOLD, int(15 * scale * DPI / 72))
    f_sub = load_font(REGULAR, int(11 * scale * DPI / 72))
    f_label = load_font(BOLD, int(9 * scale * DPI / 72))
    f_value = load_font(REGULAR, int(11 * scale * DPI / 72))

    patch = {**DEFAULT_PATCH, **mission.get("patch", {})}
    pw, ph = int(patch["width_in"] * DPI), int(patch["height_in"] * DPI)
    if portrait or stack:
        px0, py0 = SAFE, SAFE
        x, y = SAFE, py0 + ph + int(0.25 * DPI)
        max_w = cw - 2 * SAFE
    else:
        px0, py0 = SAFE, (ch - ph) // 2
        x, y = px0 + pw + int(0.30 * DPI), SAFE
        max_w = cw - SAFE - x
    shape = patch.get("shape", "rect") if mode == "land" else "rect"
    cx, cy = px0 + pw / 2, py0 + ph / 2
    if show_guide:
        if patch.get("shape") == "diamond" and mode == "land":
            d.polygon([(cx, py0), (px0 + pw, cy), (cx, py0 + ph), (px0, cy)],
                      outline=GRAY, width=2)
        elif patch.get("shape") == "round" and mode == "land":
            d.ellipse([px0, py0, px0 + pw, py0 + ph], outline=GRAY, width=2)
        else:
            d.rectangle([px0, py0, px0 + pw, py0 + ph], outline=GRAY, width=2)

    gap = int(0.20 * DPI)

    def line_x(y0, y1):
        """Left edge for a text line spanning y0..y1."""
        if shape == "rect":
            return x
        if y1 <= py0 or y0 >= py0 + ph:
            return SAFE
        dy = 0 if y0 <= cy <= y1 else min(abs(y0 - cy), abs(y1 - cy))
        t = min(1.0, dy / (ph / 2))
        hw = (pw / 2) * ((1 - t) if shape == "diamond" else (1 - t * t) ** 0.5)
        return max(SAFE, int(cx + hw + gap))

    h_over = 0
    if shape == "rect" and max_w < int(1.2 * DPI):
        h_over = int(1.2 * DPI) - max_w

    def nlines(text, font, lx):
        words, n = text.split(), 0
        lw = cw - SAFE - lx
        while words:
            line = words.pop(0)
            while words and d.textlength(f"{line} {words[0]}", font=font) <= lw:
                line += " " + words.pop(0)
            n += 1
        return n

    def block_x(y0, parts):
        """One left edge for a block of (text, font, step) parts starting at y0."""
        lx = line_x(y0, y0 + 1)
        for _ in range(4):
            h = 0
            for text, font, step in parts:
                h += nlines(text, font, lx) * int(font.size * step)
            nx = line_x(y0, y0 + h)
            if nx == lx:
                break
            lx = nx
        return lx

    def put(text, font, fill, step, lx):
        nonlocal y, h_over
        words = text.split()
        lw = cw - SAFE - lx
        while words:
            line = words.pop(0)
            while words and d.textlength(f"{line} {words[0]}", font=font) <= lw:
                line += " " + words.pop(0)
            d.text((lx, y), line, font=font, fill=fill)
            h_over = max(h_over, int(d.textlength(line, font=font)) - lw)
            if shape != "rect" and lw < int(0.9 * DPI):
                h_over = max(h_over, int(0.9 * DPI) - lw)
            y += int(font.size * step)

    head = [(mission["title"], f_title, 1.2)]
    if mission.get("subtitle"):
        head.append((mission["subtitle"], f_sub, 1.25))
    hx = block_x(y, head + [("x", f_sub, 0.6)]) if shape != "rect" else x
    for text, font, step in head:
        put(text, font, FG, step, hx)
    y += int(f_sub.size * 0.25) if mission.get("subtitle") else 0
    d.line([(hx, y), (cw - SAFE if shape != "rect" else hx + max_w, y)], fill=FG, width=3)
    y += int(0.15 * DPI)

    for field in build_fields(mission):
        parts = [(field["label"], f_label, 1.3), (field["value"], f_value, 1.25)]
        lx = block_x(y, parts) if shape != "rect" else x
        d.text((lx, y), field["label"], font=f_label, fill=GRAY)
        y += int(f_label.size * 1.3)
        put(field["value"], f_value, FG, 1.25, lx)
        y += int(0.10 * scale * DPI)

    over = max(0, y - (ch - SAFE)) + max(0, h_over)
    if (portrait or stack) and py0 + ph > ch:
        over += py0 + ph - ch
    if (portrait or stack) and px0 + pw > cw - SAFE + int(0.3 * DPI):
        over += px0 + pw - cw
    if mode == "land" and (px0 + pw > cw or ph > ch - 2 * SAFE + int(0.3 * DPI)):
        over += 1
    return img, over


def render_fit(mission, show_guide):
    """Return (image, overflow, scale, portrait). Try landscape, then
    portrait, then landscape at reduced text scale down to 0.6."""
    steps = [round(1.0 - i * SCALE_STEP, 3) for i in range(int(round((1.0 - MIN_SCALE) / SCALE_STEP)) + 1)]
    low = [round(MIN_SCALE - i * SCALE_STEP, 3) for i in range(1, 7)]
    plan = [(sc, "land") for sc in steps] + [(sc, "portrait") for sc in steps] \
        + [(sc, "stack") for sc in steps + low] + [(sc, "land") for sc in low]
    best = None
    for sc, portrait in plan:
        img, over = render(mission, show_guide, sc, portrait)
        if over == 0:
            return img, 0, sc, portrait
        if best is None or over < best[1]:
            best = (img, over, sc, portrait)
    return best


def main():
    global BG, FG, GRAY
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("data", type=Path, help="path to missions JSON")
    ap.add_argument("--out", type=Path,
                    help="output folder (default: cards, or white-cards with --white)")
    ap.add_argument("--only", nargs="*", help="render only these mission ids")
    ap.add_argument("--no-guide", action="store_true",
                    help="omit the patch outline (use for final prints)")
    ap.add_argument("--white", action="store_true",
                    help="black text on a white background")
    args = ap.parse_args()
    if args.white:
        BG, FG, GRAY = WHITE_COLORS
    if args.out is None:
        args.out = Path("white-cards" if args.white else "cards")

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
        img, over, scale, portrait = render_fit(m, show_guide=not args.no_guide)
        name = re.sub(r"[^A-Za-z0-9_-]+", "_", m["id"])
        path = args.out / f"{name}.png"
        img.save(path, dpi=(DPI, DPI))
        note = ("" if scale == 1.0 else f" (text scaled to {scale:.3f})") + (f" [{portrait}]" if portrait != "land" else "")
        print(f"Wrote {path}{note}")
        if over:
            overflowed.append((m["id"], over))

    for mid, over in overflowed:
        print(f"WARNING: {mid} overflows the safe area by {over} px",
              file=sys.stderr)


if __name__ == "__main__":
    main()
