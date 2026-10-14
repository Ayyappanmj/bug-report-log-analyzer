"""Print README Markdown for the screenshots that really exist in docs\\screenshots (valid PNG, at least 800 px wide)."""
from __future__ import annotations

import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SHOTS = ROOT / "docs" / "screenshots"
EXPECTED = [
    ("01-dashboard.png", "Dashboard: metrics measured from the demo run"),
    ("02-log-analyzer.png", "Log Analyzer with the demo log loaded"),
    ("03-error-groups.png", "Error groups with timeline"),
    ("04-root-cause.png", "Observed evidence, kept separate from the hypothesis"),
    ("05-code-explorer.png", "Verified source snippet for the failing line"),
    ("06-bug-report.png", "Reviewed Jira-ready bug report with downloads"),
]


def png_size(path: Path) -> tuple[int, int] | None:
    """(width, height) from the PNG header, or None if the file is not a PNG."""
    try:
        head = path.read_bytes()[:33]
    except OSError:
        return None
    if len(head) < 24 or head[:8] != b"\x89PNG\r\n\x1a\n" or head[12:16] != b"IHDR":
        return None
    return struct.unpack(">II", head[16:24])


def build_markdown(directory: Path = SHOTS, min_width: int = 800, rel_prefix: str = "docs/screenshots") -> tuple[str, list[str], list[str]]:
    lines, missing, rejected = [], [], []
    for name, caption in EXPECTED:
        p = directory / name
        if not p.exists():
            missing.append(name)
            continue
        size = png_size(p)
        if size is None or size[0] < min_width:
            rejected.append(f"{name} (not a PNG, or narrower than {min_width}px)")
            continue
        lines.append(f"![{caption}]({rel_prefix}/{name})")
    return "\n\n".join(lines), missing, rejected


def main() -> int:
    md, missing, rejected = build_markdown()
    if md:
        print(md + "\n")
    for r in rejected:
        print("REJECTED:", r)
    if missing:
        print("Missing (not included):", ", ".join(missing))
    return 0 if md else 1


if __name__ == "__main__":
    sys.exit(main())
