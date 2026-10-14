"""Validate docs\\demo.gif and print the README Markdown only if it is a real, reasonable GIF.  python scripts\\gif_markdown.py [path]"""
from __future__ import annotations

import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT = ROOT / "docs" / "demo.gif"


def inspect_gif(path: Path) -> dict | None:
    """Parse GIF blocks: dimensions, frame count and total duration. None if the file is not a GIF."""
    try:
        data = Path(path).read_bytes()
    except OSError:
        return None
    if len(data) < 13 or data[:6] not in (b"GIF87a", b"GIF89a"):
        return None
    width, height, packed = struct.unpack("<HHB", data[6:11])
    pos = 13 + (3 * (2 ** ((packed & 7) + 1)) if packed & 0x80 else 0)
    frames, delay_cs = 0, 0
    pending_delay = 0
    try:
        while pos < len(data):
            block = data[pos]
            if block == 0x3B:
                break
            if block == 0x21:                                   # extension
                label = data[pos + 1]
                if label == 0xF9 and data[pos + 2] >= 4:        # graphic control extension: delay in 1/100 s
                    pending_delay = struct.unpack("<H", data[pos + 4:pos + 6])[0]
                pos += 2
                while data[pos] != 0:
                    pos += data[pos] + 1
                pos += 1
            elif block == 0x2C:                                 # image descriptor
                lpacked = data[pos + 9]
                pos += 10 + (3 * (2 ** ((lpacked & 7) + 1)) if lpacked & 0x80 else 0)
                pos += 1                                        # LZW minimum code size
                while data[pos] != 0:
                    pos += data[pos] + 1
                pos += 1
                frames += 1
                delay_cs += pending_delay if pending_delay else 10
                pending_delay = 0
            else:
                return None
    except IndexError:
        return None
    return {"width": width, "height": height, "frames": frames, "duration_s": round(delay_cs / 100, 1), "size_mb": round(len(data) / (1024 * 1024), 2)}


def validate(info: dict | None) -> tuple[list[str], list[str]]:
    """(errors, warnings)."""
    if info is None:
        return ["not a valid GIF file"], []
    errors, warnings = [], []
    if info["width"] < 640:
        errors.append(f"width {info['width']} px is too small to read: record at least 960 px wide")
    if info["frames"] < 10:
        errors.append(f"only {info['frames']} frame(s): this is not a recording of the demo")
    if info["size_mb"] > 15:
        errors.append(f"{info['size_mb']} MB is too large for a README: lower fps/width or trim (target under 10 MB)")
    elif info["size_mb"] > 8:
        warnings.append(f"{info['size_mb']} MB loads slowly on GitHub: aim for under 8 MB")
    if info["duration_s"] > 90:
        errors.append(f"{info['duration_s']} s is too long: the plan is about 60 s")
    elif info["duration_s"] > 75 or info["duration_s"] < 20:
        warnings.append(f"duration {info['duration_s']} s is outside the 20-75 s range")
    if info["width"] > 1400:
        warnings.append(f"width {info['width']} px is larger than needed: 960-1280 keeps the file small")
    return errors, warnings


def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    path = Path(args[0]) if args else DEFAULT
    if not path.exists():
        print(f"{path} does not exist yet. Record the demo first (docs/demo.md); nothing was linked.")
        return 1
    info = inspect_gif(path)
    errors, warnings = validate(info)
    if info:
        print(f"{path.name}: {info['width']}x{info['height']}, {info['frames']} frames, {info['duration_s']} s, {info['size_mb']} MB")
    for w in warnings:
        print("warning:", w)
    for e in errors:
        print("ERROR:", e)
    if errors:
        return 1
    rel = path.resolve().relative_to(ROOT).as_posix() if str(path.resolve()).startswith(str(ROOT)) else path.name
    print(f"\nPaste into the Demo section of README.md (and delete the 'No recording has been made yet' sentence):\n\n![Demo of the analyzer](" + rel + ")")
    return 0


if __name__ == "__main__":
    sys.exit(main())
