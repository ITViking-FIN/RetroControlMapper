"""
Clean a single-controller product photo for use in the GUI catalog.

Three modes:

Tier A (default): tight bounding-box crop — keeps the original background.
                  Looks like a "product card" against the dark UI.

Tier B (--remove-bg): corner-flood background replacement. Samples the
                  four corners to determine background colour and replaces
                  similar pixels with the GUI panel colour. Works well when
                  the background is uniform; struggles with anti-aliased
                  edges on light-on-light photos (faint halo possible).

Tier C (--silhouette): for dark-on-light source photos. Extracts the
                  controller silhouette, renders it as a light-coloured
                  shape on the dark UI panel, optionally preserving
                  saturated regions (coloured letters / LEDs). Best for
                  black controllers that would otherwise vanish on a dark
                  UI.

Usage:
    py clean_controller_photo.py <input> --out <path>
        [--remove-bg | --silhouette]
        [--silhouette-color "200,205,210"] [--keep-colors] [--threshold 200]
        [--max-side 800] [--tolerance 18] [--feather 6]

Examples:
    # Tight crop, keep background
    py clean_controller_photo.py 8bitdo-ult.jpg --out gui/img/known/2DC8_3106.jpg

    # Best-effort background removal
    py clean_controller_photo.py 8bitdo-ult.jpg --out gui/img/known/2DC8_3106.png --remove-bg

    # Black controller → light silhouette icon, preserve coloured letters
    py clean_controller_photo.py ultimate2-black.jpg --out gui/img/known/2DC8_310B.png \
        --silhouette --keep-colors
"""
from __future__ import annotations
import argparse
import sys
from pathlib import Path

from PIL import Image, ImageFilter, ImageDraw, ImageChops

PANEL_BG_RGB = (13, 17, 23)  # #0d1117 — RB-Controller_fix dark panel


def find_object_bbox(im: Image.Image, bg_tol: int = 25) -> tuple[int, int, int, int] | None:
    """Find the bounding box of the controller (non-background pixels).

    We sample the four corners to estimate the background colour, then build
    a mask of pixels DIFFERENT from that background by more than `bg_tol`.
    Returns (left, top, right, bottom) or None if no object found.
    """
    w, h = im.size
    rgb = im.convert("RGB")
    corner_samples = []
    for x, y in [(0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1),
                 (5, 5), (w - 6, 5), (5, h - 6), (w - 6, h - 6)]:
        corner_samples.append(rgb.getpixel((x, y)))
    bg = tuple(sum(c[i] for c in corner_samples) // len(corner_samples) for i in range(3))

    # Build absdiff image: max channel-difference from bg
    bg_layer = Image.new("RGB", (w, h), bg)
    diff = ImageChops.difference(rgb, bg_layer).convert("L")
    mask = diff.point(lambda p: 255 if p > bg_tol else 0)
    # Slightly close gaps (controller may have small white-ish patches)
    mask = mask.filter(ImageFilter.MaxFilter(5))
    bbox = mask.getbbox()
    return bbox


def remove_background(im: Image.Image, tolerance: int = 18, feather: int = 6) -> Image.Image:
    """Replace near-background pixels with PANEL_BG_RGB. Uses corner-sampled
    background colour + tolerance + soft feather for the boundary."""
    w, h = im.size
    rgb = im.convert("RGB")

    # Sample corners as background reference
    samples = []
    for x, y in [(0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1),
                 (5, 5), (w - 6, 5), (5, h - 6), (w - 6, h - 6)]:
        samples.append(rgb.getpixel((x, y)))
    bg = tuple(sum(c[i] for c in samples) // len(samples) for i in range(3))

    # Build diff mask
    bg_layer = Image.new("RGB", (w, h), bg)
    diff = ImageChops.difference(rgb, bg_layer).convert("L")
    # Pixels far from bg → keep (mask 255). Close to bg → replace (mask 0).
    mask = diff.point(lambda p: 255 if p > tolerance else 0)
    # Feather the boundary so anti-aliased edges blend gracefully
    if feather > 0:
        mask = mask.filter(ImageFilter.GaussianBlur(feather))
    panel = Image.new("RGB", (w, h), PANEL_BG_RGB)
    return Image.composite(rgb, panel, mask)


def silhouette(im: Image.Image, fill_rgb: tuple[int, int, int] = (200, 205, 210),
               threshold: int = 200, keep_colors: bool = True,
               feather: int = 2) -> Image.Image:
    """Tier C: turn a dark-on-light photo into a light silhouette on the
    dark UI panel.

    Strategy:
      1. Build a "controller mask" = pixels darker than `threshold`
      2. Fill the masked area with `fill_rgb`
      3. If `keep_colors`, overlay original saturated pixels on top so
         coloured letters / LED rings survive the recolour
      4. Composite onto the dark panel background
    """
    w, h = im.size
    rgb = im.convert("RGB")
    gray = rgb.convert("L")

    # Mask: pixels darker than threshold are part of the controller body
    body_mask = gray.point(lambda p: 255 if p < threshold else 0)
    if feather > 0:
        body_mask = body_mask.filter(ImageFilter.GaussianBlur(feather))

    # Build the light-coloured silhouette
    fill_layer = Image.new("RGB", (w, h), fill_rgb)

    # Start with dark panel background
    panel = Image.new("RGB", (w, h), PANEL_BG_RGB)

    # Composite: where body_mask, show fill_layer; else show panel
    result = Image.composite(fill_layer, panel, body_mask)

    if keep_colors:
        # Saturated-pixel overlay: anywhere the original was strongly
        # coloured (high saturation), restore the original colour on top.
        hsv = rgb.convert("HSV")
        _, s_band, v_band = hsv.split()
        # High saturation AND not-too-dark (avoids picking up noise)
        sat_mask = Image.eval(s_band, lambda p: 255 if p > 80 else 0)
        # Soft so the colour blends rather than hard-edging
        sat_mask_soft = sat_mask.filter(ImageFilter.GaussianBlur(1))
        result = Image.composite(rgb, result, sat_mask_soft)

    return result


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
    ap.add_argument("input", type=Path)
    ap.add_argument("--out", type=Path, required=True,
                    help="Output path (.jpg or .png).")
    ap.add_argument("--remove-bg", action="store_true",
                    help="Tier B: corner-flood background replacement.")
    ap.add_argument("--silhouette", action="store_true",
                    help="Tier C: dark-on-light photo → light silhouette on dark panel.")
    ap.add_argument("--silhouette-color", default="200,205,210",
                    help="Tier C: silhouette fill colour as 'R,G,B'. Default 200,205,210.")
    ap.add_argument("--keep-colors", action="store_true", default=True,
                    help="Tier C: preserve coloured letters/LEDs (default on).")
    ap.add_argument("--no-keep-colors", dest="keep_colors", action="store_false",
                    help="Tier C: pure white silhouette, no preserved colours.")
    ap.add_argument("--threshold", type=int, default=200,
                    help="Tier C: pixels darker than this are part of the silhouette.")
    ap.add_argument("--tolerance", type=int, default=18,
                    help="Tier B: how close-to-bg counts as background (0-255). Default 18.")
    ap.add_argument("--feather", type=int, default=6,
                    help="Tier B: soft-edge blur radius. Default 6.")
    ap.add_argument("--max-side", type=int, default=800)
    ap.add_argument("--padding", type=int, default=20,
                    help="Pixels to pad around the detected object bbox.")
    args = ap.parse_args()

    if not args.input.exists():
        print(f"[fatal] input not found: {args.input}", file=sys.stderr)
        sys.exit(1)

    im = Image.open(args.input).convert("RGB")
    w, h = im.size
    print(f"input: {args.input.name}  {w}x{h}")

    bbox = find_object_bbox(im)
    if bbox is None:
        print("[warn] no distinct object found; using full image")
        bbox = (0, 0, w, h)
    x1, y1, x2, y2 = bbox
    p = args.padding
    x1 = max(0, x1 - p); y1 = max(0, y1 - p)
    x2 = min(w, x2 + p); y2 = min(h, y2 + p)
    cropped = im.crop((x1, y1, x2, y2))
    print(f"cropped to {x1},{y1} -> {x2},{y2}  ({cropped.size[0]}x{cropped.size[1]})")

    if args.remove_bg and args.silhouette:
        print("[fatal] choose ONE of --remove-bg or --silhouette", file=sys.stderr)
        sys.exit(1)
    if args.remove_bg:
        cropped = remove_background(cropped, args.tolerance, args.feather)
        print(f"applied background removal (tolerance={args.tolerance}, feather={args.feather})")
    elif args.silhouette:
        try:
            r, g, b = [int(v.strip()) for v in args.silhouette_color.split(",")]
        except (ValueError, AttributeError):
            print(f"[fatal] bad --silhouette-color: '{args.silhouette_color}'", file=sys.stderr)
            sys.exit(1)
        cropped = silhouette(cropped, fill_rgb=(r, g, b),
                             threshold=args.threshold,
                             keep_colors=args.keep_colors,
                             feather=2)
        print(f"applied silhouette mode (threshold={args.threshold}, "
              f"fill={r},{g},{b}, keep_colors={args.keep_colors})")

    cropped = fit(cropped, args.max_side)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    suffix = args.out.suffix.lower() or ".jpg"
    if suffix == ".jpg":
        cropped.save(args.out, "JPEG", quality=88, optimize=True)
    elif suffix == ".png":
        cropped.save(args.out, "PNG", optimize=True)
    else:
        cropped.save(args.out)
    print(f"saved -> {args.out}")


if __name__ == "__main__":
    main()
