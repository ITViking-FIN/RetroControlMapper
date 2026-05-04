"""
RetroBat bezel calibrator.

For every <System>.png in the decorations folder, computes the transparent
bounding box and writes a paired <System>.info JSON sidecar so RetroBat uses
the calibrated value instead of falling back to its alpha<235 auto-detect
(which is too lenient — anti-aliased and glass-effect pixels get treated as
play area, producing an over-generous viewport that lets the game render past
the bezel frame).

The .info format matches RetroBat's expected schema (width/height = bezel
image native res; top/left/bottom/right = opaque-frame margins on each side).

Usage:
    py calibrate_bezels.py                # apply with defaults
    py calibrate_bezels.py --dry-run      # preview, no writes
    py calibrate_bezels.py --threshold 16 # tighter alpha cutoff
    py calibrate_bezels.py --threshold 235 # mimic RetroBat default (debug)

Default threshold = 32: only pixels with alpha <= 32 are treated as play area.
This excludes anti-aliased frame edges and glass effects.
"""
from __future__ import annotations
import argparse
import json
import shutil
import sys
from pathlib import Path
from PIL import Image

from config import BEZELS_DIR as BEZEL_DIR


def find_play_area(img: Image.Image, alpha_threshold: int):
    """Return (left, top, right, bottom) of the bounding box of pixels with
    alpha <= alpha_threshold. Coords are inclusive-exclusive PIL bbox style.
    Returns None if no qualifying pixels."""
    if img.mode != "RGBA":
        img = img.convert("RGBA")
    alpha = img.split()[3]
    mask = alpha.point(lambda p: 255 if p <= alpha_threshold else 0)
    return mask.getbbox()


def margins_from_bbox(bbox, w, h):
    """Convert PIL bbox (l,t,r,b) into RetroBat margin dict."""
    l, t, r, b = bbox
    return {
        "left": l,
        "top": t,
        "right": w - r,
        "bottom": h - b,
    }


def write_info(png: Path, w: int, h: int, margins: dict, dry_run: bool):
    info_path = png.with_suffix(".info")
    info = {
        "width": w,
        "height": h,
        "top": margins["top"],
        "left": margins["left"],
        "bottom": margins["bottom"],
        "right": margins["right"],
        "opacity": 1.0,
        "messagex": 0.220000,
        "messagey": 0.120000,
    }
    body = json.dumps(info, indent=3) + "\n"
    if dry_run:
        return False
    if info_path.exists():
        shutil.copy2(info_path, info_path.with_suffix(".info.bak"))
    info_path.write_text(body, encoding="utf-8")
    return True


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--threshold", type=int, default=32,
                    help="Alpha threshold (0..255). Pixels with alpha <= threshold "
                         "count as play-area. Default 32. RetroBat's auto-detect uses 235.")
    ap.add_argument("--dry-run", action="store_true",
                    help="Print results, don't write .info files.")
    ap.add_argument("--bezel-dir", type=Path, default=BEZEL_DIR,
                    help="Override the bezel directory.")
    args = ap.parse_args()

    if not args.bezel_dir.exists():
        print(f"[fatal] bezel dir not found: {args.bezel_dir}", file=sys.stderr)
        sys.exit(1)

    pngs = sorted(args.bezel_dir.glob("*.png"))
    if not pngs:
        print(f"[fatal] no PNGs in {args.bezel_dir}", file=sys.stderr)
        sys.exit(1)

    print(f"Scanning {len(pngs)} bezels in {args.bezel_dir}")
    print(f"Alpha threshold: <= {args.threshold} (lower = stricter play-area)")
    print(f"{'(dry run — no files written)' if args.dry_run else 'Writing .info files alongside PNGs.'}\n")

    written = skipped = warned = failed = 0
    anomalies = []

    print(f"{'System':<28} {'Image WxH':>14} {'Play area WxH':>16} {'Ratio':>8} {'Margins L/T/R/B':>22}")
    print("-" * 100)

    for png in pngs:
        try:
            with Image.open(png) as im:
                w, h = im.size
                bbox = find_play_area(im, args.threshold)
                if bbox is None:
                    print(f"{png.stem:<28} {w}x{h:<10}   (no transparent area)")
                    skipped += 1
                    continue
                m = margins_from_bbox(bbox, w, h)
                play_w, play_h = w - m["left"] - m["right"], h - m["top"] - m["bottom"]
                ratio = play_w / play_h if play_h else 0
                print(f"{png.stem:<28} {w}x{h:<8} {play_w}x{play_h:<8} {ratio:>7.3f}  "
                      f"{m['left']:>4}/{m['top']:>4}/{m['right']:>4}/{m['bottom']:>4}")

                # Sanity-check anomalies
                note = []
                if play_w / w < 0.3 or play_h / h < 0.3:
                    note.append("play-area < 30% of image")
                if play_w / w > 0.99 and play_h / h > 0.99:
                    note.append("play-area covers entire image (PNG may be all-transparent)")
                if not (1.20 <= ratio <= 1.40 or 1.30 <= ratio <= 1.80):
                    # Allow 4:3 and 16:9-ish; warn for weird ratios
                    if not (1.0 <= ratio <= 2.0):
                        note.append(f"unusual aspect {ratio:.2f}")
                if note:
                    warned += 1
                    anomalies.append((png.stem, ", ".join(note)))

                if write_info(png, w, h, m, args.dry_run):
                    written += 1
        except Exception as e:
            print(f"[fail] {png.name}: {e}")
            failed += 1

    print("\n" + "-" * 100)
    print(f"Summary: {written} written, {skipped} skipped (no transparency), "
          f"{warned} with anomalies, {failed} failed.")
    if anomalies:
        print("\nAnomalies (review these manually):")
        for name, msg in anomalies:
            print(f"  - {name}: {msg}")


if __name__ == "__main__":
    main()
