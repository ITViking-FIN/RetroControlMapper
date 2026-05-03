"""
Isolate individual controllers from a side-by-side product photo.

Designed for the 8BitDo Ultimate 2 Wireless pair photo (white + black on a
brick wall background) but the technique generalises: scan column-summed
darkness, find the two largest dark/light "blobs" along the X axis,
crop each tightly with padding, optionally fade the borders to dark so the
crop blends into the GUI's #0d1117 panel background.

Usage:
    py isolate_controllers.py <input.jpg>
        [--out-black <path>] [--out-white <path>]
        [--fade] [--max-side 900] [--debug]

Defaults:
    --out-black: gui/img/known/2DC8_310B.jpg   (8BitDo Ultimate 2 PID)
    --out-white: gui/img/contrib/8bitdo-ultimate2-white.jpg
    --max-side:  900px (the larger dimension of the cropped output)
"""
from __future__ import annotations
import argparse
import sys
from pathlib import Path

from PIL import Image, ImageFilter, ImageDraw

ROOT = Path(__file__).resolve().parent
DEFAULT_BLACK = ROOT / "gui" / "img" / "known" / "2DC8_310B.jpg"
DEFAULT_WHITE = ROOT / "gui" / "img" / "contrib" / "8bitdo-ultimate2-white.jpg"


def find_controller_columns(im: Image.Image, n_blobs: int = 2):
    """Return n_blobs (x_start, x_end) tuples spanning the width.

    Strategy:
    - Convert to grayscale
    - For each column, compute mean luminance variance from the row mean
      (controller silhouettes are coherent vertically; brick is noisy)
    - Smooth the variance across columns
    - Find the n_blobs widest local maxima above a threshold
    """
    g = im.convert("L")
    w, h = g.size
    # Sample every Nth row to keep it fast
    step = max(1, h // 200)
    rows = []
    for y in range(0, h, step):
        rows.append(list(g.crop((0, y, w, y + 1)).getdata()))

    # Column-wise standard deviation across sampled rows
    n_rows = len(rows)
    col_var = [0.0] * w
    for x in range(w):
        col_vals = [rows[r][x] for r in range(n_rows)]
        m = sum(col_vals) / n_rows
        var = sum((v - m) ** 2 for v in col_vals) / n_rows
        col_var[x] = var

    # Smooth via box average
    smooth_n = max(8, w // 200)
    smoothed = []
    for x in range(w):
        a = max(0, x - smooth_n)
        b = min(w, x + smooth_n)
        smoothed.append(sum(col_var[a:b]) / (b - a))

    # Brick varies a lot due to mortar lines; controllers vary less because
    # of large flat regions. So we look for LOW-variance bands separated by
    # high-variance brick. Invert: focus = max(smoothed) - smoothed[x].
    peak = max(smoothed)
    focus = [peak - v for v in smoothed]
    threshold = sum(focus) / len(focus) * 1.15  # mean × 1.15

    # Find contiguous regions where focus > threshold; pick widest n_blobs
    regions = []
    start = None
    for x, f in enumerate(focus):
        if f > threshold:
            if start is None:
                start = x
        else:
            if start is not None:
                regions.append((start, x))
                start = None
    if start is not None:
        regions.append((start, w))

    # Filter tiny regions and sort by width descending
    regions = [(a, b) for a, b in regions if (b - a) >= w * 0.05]
    regions.sort(key=lambda r: r[1] - r[0], reverse=True)
    chosen = sorted(regions[:n_blobs], key=lambda r: r[0])  # left-to-right
    return chosen


def find_vertical_extent(im_crop: Image.Image, padding_frac: float = 0.04):
    """Within a column-cropped slice, find the vertical extent of the
    actual controller (skip the dark wood floor + brick header)."""
    g = im_crop.convert("L")
    w, h = g.size
    step = max(1, w // 200)
    cols = []
    for x in range(0, w, step):
        cols.append(list(g.crop((x, 0, x + 1, h)).getdata()))
    n_cols = len(cols)
    row_var = [0.0] * h
    for y in range(h):
        vals = [cols[c][y] for c in range(n_cols)]
        m = sum(vals) / n_cols
        var = sum((v - m) ** 2 for v in vals) / n_cols
        row_var[y] = var

    # Controller has more variation than empty wood/brick rows
    smooth_n = max(8, h // 100)
    smoothed = []
    for y in range(h):
        a = max(0, y - smooth_n)
        b = min(h, y + smooth_n)
        smoothed.append(sum(row_var[a:b]) / (b - a))

    threshold = max(smoothed) * 0.45
    top, bottom = 0, h
    for y in range(h):
        if smoothed[y] > threshold:
            top = y
            break
    for y in range(h - 1, -1, -1):
        if smoothed[y] > threshold:
            bottom = y
            break
    pad = int(h * padding_frac)
    return max(0, top - pad), min(h, bottom + pad)


def feather_edges(im: Image.Image, fade_px: int = 24) -> Image.Image:
    """Apply a soft gradient to the edges so the crop blends into a dark
    panel (#0d1117). Returns a new image."""
    w, h = im.size
    mask = Image.new("L", (w, h), 255)
    draw = ImageDraw.Draw(mask)
    for i in range(fade_px):
        alpha = int(255 * (i / fade_px))
        draw.rectangle([i, i, w - 1 - i, h - 1 - i], outline=alpha)
    bg = Image.new("RGB", (w, h), (13, 17, 23))  # #0d1117
    blended = Image.composite(im, bg, mask.filter(ImageFilter.GaussianBlur(fade_px / 4)))
    return blended


def fit(im: Image.Image, max_side: int) -> Image.Image:
    w, h = im.size
    if max(w, h) <= max_side:
        return im
    if w >= h:
        nw = max_side; nh = int(h * max_side / w)
    else:
        nh = max_side; nw = int(w * max_side / h)
    return im.resize((nw, nh), Image.LANCZOS)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input", type=Path, help="Path to the side-by-side photo.")
    ap.add_argument("--out-black", type=Path, default=DEFAULT_BLACK)
    ap.add_argument("--out-white", type=Path, default=DEFAULT_WHITE)
    ap.add_argument("--fade", action="store_true",
                    help="Feather edges toward the dark panel background.")
    ap.add_argument("--max-side", type=int, default=900)
    ap.add_argument("--debug", action="store_true",
                    help="Save annotated debug image showing detected regions.")
    args = ap.parse_args()

    if not args.input.exists():
        print(f"[fatal] input not found: {args.input}", file=sys.stderr)
        sys.exit(1)

    im = Image.open(args.input).convert("RGB")
    w, h = im.size
    print(f"input: {args.input.name}  {w}x{h}")

    cols = find_controller_columns(im, n_blobs=2)
    if len(cols) < 2:
        print(f"[warn] only found {len(cols)} controller column-region(s); falling back to halves")
        mid = w // 2
        cols = [(int(w * 0.05), mid - 10), (mid + 10, int(w * 0.95))]

    print("detected column regions:")
    for i, (a, b) in enumerate(cols):
        print(f"  region {i}: x={a}..{b}  ({b - a}px)")

    if args.debug:
        dbg = im.copy()
        d = ImageDraw.Draw(dbg)
        for a, b in cols:
            d.rectangle([a, 0, b, h - 1], outline=(255, 0, 255), width=4)
        dbg_path = args.input.with_suffix(".debug.jpg")
        dbg.save(dbg_path, "JPEG", quality=85)
        print(f"  debug image -> {dbg_path}")

    # Convention: left column = white, right column = black
    targets = [
        (cols[0], args.out_white, "white"),
        (cols[1], args.out_black, "black"),
    ]
    for (x1, x2), out, label in targets:
        slice_ = im.crop((x1, 0, x2, h))
        y1, y2 = find_vertical_extent(slice_)
        controller = im.crop((x1, y1, x2, y2))
        controller = fit(controller, args.max_side)
        if args.fade:
            controller = feather_edges(controller, fade_px=int(min(controller.size) * 0.04))
        out.parent.mkdir(parents=True, exist_ok=True)
        # Pick suffix from existing extension OR force jpg
        suffix = out.suffix.lower() or ".jpg"
        if suffix == ".jpg":
            controller.save(out, "JPEG", quality=88, optimize=True)
        elif suffix == ".png":
            controller.save(out, "PNG", optimize=True)
        else:
            controller.save(out)
        print(f"  {label}: {x1},{y1} -> {x2},{y2}  saved to {out}")

    print("done.")


if __name__ == "__main__":
    main()
