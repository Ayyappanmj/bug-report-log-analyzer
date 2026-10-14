"""Keeps the README and docs honest: every link, path and command must exist, and nothing may be claimed that the repo cannot back."""
import re
import tempfile
from pathlib import Path

from scripts.screenshot_markdown import EXPECTED, build_markdown, png_size

ROOT = Path(__file__).resolve().parent.parent
README = (ROOT / "README.md").read_text(encoding="utf-8")
DOCS = [ROOT / "README.md", ROOT / "SECURITY.md", ROOT / ".env.example", *sorted((ROOT / "docs").glob("*.md"))]
TOP_LEVEL = {p.name for p in ROOT.iterdir() if not p.name.startswith(".git")}


def test_required_sections_exist():
    for heading in ("The problem", "The solution", "Features", "Architecture", "How it works", "Tech stack", "Demo", "Screenshots",
                    "Installation", "Run", "Optional: local LLM with Ollama", "Testing", "Benchmarking", "Project structure",
                    "Security", "Limitations", "Future improvements", "License"):
        assert re.search(rf"^## .*{re.escape(heading)}", README, flags=re.M), heading


def test_mermaid_diagrams_are_present_and_balanced():
    for path in (ROOT / "README.md", ROOT / "docs" / "architecture.md"):
        blocks = re.findall(r"```mermaid\n(.*?)```", path.read_text(encoding="utf-8"), flags=re.S)
        assert blocks, path.name
        for block in blocks:
            first = block.strip().splitlines()[0]
            assert re.match(r"(flowchart (TD|LR)|sequenceDiagram)", first), first
            for pair in ("[]", "()", "{}"):
                assert block.count(pair[0]) == block.count(pair[1]), (path.name, pair)
            assert block.count('"') % 2 == 0
    readme_diagram = re.findall(r"```mermaid\n(.*?)```", README, flags=re.S)[0]
    for node in ("Streamlit UI", "Agent controller", "Log analyzer", "Code scanner", "Root-cause analyzer", "Bug report builder", "Human review"):
        assert node in readme_diagram, node


def test_every_relative_link_and_path_exists():
    for doc in DOCS:
        if doc.suffix != ".md":
            continue
        text = doc.read_text(encoding="utf-8")
        for target in re.findall(r"\]\((?!https?://|#|mailto:)([^)\s]+)\)", text):
            path = (doc.parent / target.split("#")[0]).resolve()
            assert path.exists(), f"{doc.name}: broken link {target}"
        for code in re.findall(r"`([A-Za-z0-9_./\\-]+\.(?:md|py|ps1|toml|yml|txt|ini|json|example))`", text):
            norm = code.replace("\\", "/")
            if norm.split("/")[0] in TOP_LEVEL and "<" not in norm and "*" not in norm and not norm.startswith("benchmarks/results"):
                if norm.startswith(("out/", "docs/screenshots/")) or norm in ("workflow-times.jsonl",):
                    continue
                assert (ROOT / norm).exists() or (doc.parent / norm).exists(), f"{doc.name}: `{code}` does not exist"


def test_commands_in_the_docs_refer_to_real_scripts():
    for doc in DOCS:
        for script in re.findall(r"python\s+scripts[\\/]+(\w+\.py)", doc.read_text(encoding="utf-8")):
            assert (ROOT / "scripts" / script).exists(), f"{doc.name}: scripts/{script}"
        for ps in re.findall(r"\.\\scripts\\(\w+\.ps1)", doc.read_text(encoding="utf-8")):
            assert (ROOT / "scripts" / ps).exists()
    for needed in ("streamlit run app.py", "pytest", "python -m venv .venv", r".venv\Scripts\activate", "pip install -r requirements.txt",
                   "ollama pull", "Python 3.11"):
        assert needed in README, needed


def test_readme_makes_no_unbacked_claims():
    low = README.lower()
    for banned in (r"production[- ]ready", r"\d+(\.\d+)?\s*(x|×)\s*faster", r"\b\d+\s*%\s*(test )?(coverage|accuracy|precision)", r"enterprise[- ]grade",
                   r"100%\s*(secure|safe|accurate)", r"\bscales? to\b", r"\bmillions? of (lines|events|logs)"):
        assert not re.search(banned, low), banned
    assert not re.search(r"\b\d+(\.\d+)?\s*(mb/s|seconds|ms|minutes)\b", low), "performance numbers belong in your own benchmark output"
    assert "no screenshots are included yet" in low or "![" in README
    assert "no recording has been made yet" in low or (ROOT / "docs" / "demo.gif").exists()


def test_media_is_referenced_only_if_it_exists():
    for target in re.findall(r"!\[[^\]]*\]\(([^)]+)\)", README):
        assert (ROOT / target).exists(), f"README embeds missing image {target}"
    if "docs/demo.gif" in README:
        assert (ROOT / "docs" / "demo.gif").exists()
    shots = list((ROOT / "docs" / "screenshots").glob("*.png"))
    if shots:
        assert "![" in README, "screenshots exist but the README does not show them: run scripts\\screenshot_markdown.py"


def test_documents_contain_no_invented_urls():
    allowed = ("ollama.com", "localhost", "127.0.0.1", "your-team.atlassian.net", "jira.example", "example.com", "example.org", "evil.example")
    for doc in DOCS:
        for url in re.findall(r"https?://([A-Za-z0-9.-]+)", doc.read_text(encoding="utf-8")):
            assert url.endswith(allowed) or any(url == a or url.endswith("." + a) for a in allowed), f"{doc.name}: unexpected URL host {url}"


def test_project_structure_table_matches_the_repository():
    section = README.split("## Project structure")[1].split("## ")[0]
    for names in re.findall(r"^\| ((?:`[^`]+`(?:, )?)+) \|", section, flags=re.M):
        for item in re.findall(r"`([^`]+)`", names):
            assert (ROOT / item.rstrip("/")).exists(), item
    for folder in ("agent", "log_analyzer", "code_analyzer", "ai", "reports", "storage", "security", "ui", "tests", "docs", "demo"):
        assert f"`{folder}/`" in section, folder


def test_portfolio_card_is_honest():
    text = (ROOT / "docs" / "portfolio.md").read_text(encoding="utf-8")
    for needed in ("Bug Report & Log Analyzer Agent", "Python", "Streamlit", "Ollama", "Pydantic", "SQLite", "pytest", "Run Locally",
                   "GitHub", "Demo Video", "Case Study"):
        assert needed in text, needed
    assert "http" not in text and "<your repository URL" in text
    case = (ROOT / "docs" / "case_study.md").read_text(encoding="utf-8")
    assert "[X MB]" in case and "Fill the bracketed items" in case                  # numbers are placeholders, not claims


def test_screenshot_helper_accepts_only_real_wide_pngs():
    import struct
    import zlib

    def png(width, height):
        ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
        return b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + ihdr + struct.pack(">I", zlib.crc32(b"IHDR" + ihdr)) + b"\x00" * 20
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        (d / EXPECTED[0][0]).write_bytes(png(1600, 900))
        (d / EXPECTED[1][0]).write_bytes(png(300, 200))                 # too narrow
        (d / EXPECTED[2][0]).write_bytes(b"not a png at all, just text" * 10)
        md, missing, rejected = build_markdown(d)
        assert md == f"![{EXPECTED[0][1]}](docs/screenshots/{EXPECTED[0][0]})"
        assert len(rejected) == 2 and len(missing) == 3 and png_size(d / EXPECTED[0][0]) == (1600, 900)
    assert png_size(ROOT / "README.md") is None and png_size(ROOT / "nope.png") is None
