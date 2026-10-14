import contextlib
import io
import os
import re
import socket
import struct
import tempfile
from pathlib import Path
from unittest.mock import patch

from scripts import demo_check as DC
from scripts import demo_rehearsal as DR
from scripts import gif_markdown as GM
from scripts.demo_plan import SEGMENTS, TOTAL_SECONDS, plain
from scripts.generate_demo_log import build_log
from tests.fake_streamlit import installed, page

ROOT = Path(__file__).resolve().parent.parent


# ------------------------------------------------------------------ the plan itself
def test_plan_matches_the_requested_timeline():
    assert [(s.start, s.end) for s in SEGMENTS] == [(0, 5), (5, 10), (10, 20), (20, 30), (30, 40), (40, 50), (50, 60)] and TOTAL_SECONDS == 60
    assert [s.title for s in SEGMENTS] == ["Open the dashboard", "Load the demo", "Analyze the log", "Show the detected incident",
                                          "Show the root cause", "Show the source code", "Generate the Jira report"]
    assert all(s.say.strip() and s.action.strip() for s in SEGMENTS)
    words = sum(len(s.say.split()) for s in SEGMENTS)
    assert words / TOTAL_SECONDS < 2.0, "narration is too long to speak calmly in the time"
    for s in SEGMENTS:
        assert len(s.say.split()) / s.length < 2.8, f"{s.title}: {len(s.say.split())} words in {s.length} s is too fast to say clearly"


def test_every_label_in_the_plan_is_clickable_in_the_real_ui():
    """Walks the real page code (fake Streamlit) and collects every button, tab, checkbox, download and sidebar label."""
    with tempfile.TemporaryDirectory() as tmp, installed() as st:
        os.environ["DB_PATH"] = str(Path(tmp) / "h.db")
        try:
            from ui import state as S
            S.init()
            seen = set()

            def harvest():
                for kind, args, kw in st.calls:
                    if kind in ("button", "checkbox", "toggle") and args:
                        seen.add(str(args[0]))
                    elif kind in ("tabs", "radio") and args:
                        seen.update(map(str, args[0]))
                seen.update(d[0] for d in st.downloads)
                st.calls.clear()
            page("dashboard").render()
            S.load_demo()
            st.click("analyze")
            page("analyzer").render()
            for name in ("error_groups", "root_cause", "code_viewer", "reports"):
                page(name).render()
            harvest()
            app_src = (ROOT / "app.py").read_text(encoding="utf-8")
            assert "radio" in app_src
            seen.update(S.PAGES)
        finally:
            os.environ.pop("DB_PATH", None)
    for seg in SEGMENTS:
        for label in seg.labels():
            assert label in seen, f"segment '{seg.title}' tells the presenter to use '{label}', which the UI does not offer"


def test_demo_guide_table_is_the_plan():
    doc = (ROOT / "docs" / "demo.md").read_text(encoding="utf-8")
    for seg in SEGMENTS:
        mm = lambda s: "1:00" if s == 60 else f"0:{s:02d}"  # noqa: E731
        row = f"| {mm(seg.start)}–{mm(seg.end)} | {seg.title} | {seg.action} | {seg.say} |"
        assert row in doc, seg.title
    for needed in ("demo_check.py", "demo_rehearsal.py", "gif_markdown.py", "Win+Alt+R", "ScreenToGif", "OBS Studio", "ffmpeg", "palettegen",
                   "No recording exists yet", "Focus Assist"):
        assert needed in doc, needed
    assert not (ROOT / "docs" / "demo.gif").exists() or "![" in (ROOT / "README.md").read_text(encoding="utf-8")


# ------------------------------------------------------------------ rehearsal
def scripted(n=100):
    it = iter([""] * n)
    return lambda prompt="": next(it)


def ticking(values):
    it = iter(values)
    return lambda: next(it)


def test_rehearsal_reports_pace_against_the_plan():
    lines = []
    clock = ticking([0.0, 5.0, 10.0, 25.0, 30.0, 40.0, 50.0, 60.0])             # start, then the end time of each of the 7 segments
    res = DR.run_rehearsal(input_fn=scripted(), clock=clock, out=lines.append)
    assert res["total"] == 60.0 and res["verdict"] == "on time" and [r["actual"] for r in res["rows"]] == [5, 5, 15, 5, 10, 10, 10]
    text = "\n".join(lines)
    assert "DO:" in text and "SAY:" in text and "**" not in text and "Analyze the log" in text and "<-- slow" in text and "10-20" in text.replace(" ", "")


def test_rehearsal_flags_an_overrun():
    res = DR.run_rehearsal(input_fn=scripted(), clock=ticking([0.0, 8, 16, 30, 45, 60, 72, 85]), out=lambda *_: None)
    assert "over by 25 s" in res["verdict"] and res["rows"][-1]["over_by"] == 25.0 and res["rows"][0]["over_by"] == 3.0


def test_plain_strips_bold_markers():
    assert plain("Click **Analyze** now") == "Click Analyze now"


# ------------------------------------------------------------------ readiness check
def test_demo_data_checks_pass_and_detect_tampering(tmp_path):
    assert all(c.ok for c in DC.check_demo_data())
    bad = tmp_path / "log.log"
    bad.write_text(build_log() + "an extra line\n", encoding="utf-8")
    checks = DC.check_demo_data(bad, DC.DEMO_PROJECT)
    assert [c.ok for c in checks] == [True, True, False] and "generate_demo_log.py" in checks[2].detail
    missing = DC.check_demo_data(tmp_path / "nope.log", tmp_path / "noproj")
    assert [c.ok for c in missing] == [False, False]


def test_expected_screen_values_come_from_a_real_run():
    v = DC.expected_screen_values()
    assert list(v["cards"]) == ["Total Events", "Unique Errors", "Critical Errors", "Recurring Errors", "Files Analyzed", "Analysis Duration"]
    assert v["code_verified"] and v["first_file"] == "src/database.py" and v["top_group"].startswith("G001") and v["top_severity"] == "HIGH"
    assert int(v["cards"]["Total Events"].replace(",", "")) > 3000


def test_port_check():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        s.listen(1)
        busy = s.getsockname()[1]
        assert DC.port_free(busy) is False
    assert DC.port_free(busy) is True


def run_main(args, streamlit=True, env=None):
    buf = io.StringIO()
    with patch.object(DC, "streamlit_installed", lambda: streamlit), contextlib.redirect_stdout(buf):
        old = {k: os.environ.get(k) for k in (env or {})}
        os.environ.update(env or {})
        try:
            code = DC.main(args)
        finally:
            for k, v in old.items():
                os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
    return code, buf.getvalue()


def test_demo_check_main_prints_what_to_expect_or_fails_clearly():
    code, out = run_main([])
    assert code == 0 and "What you should see on screen" in out and "Total Events:" in out and "code verified: True" in out
    assert "rehearse" in out.lower()
    code, out = run_main([], streamlit=False)
    assert code == 1 and "[FAIL] streamlit is installed" in out and "What you should see" not in out


def test_history_is_only_deleted_with_the_explicit_flag(tmp_path):
    db = tmp_path / "history.db"
    db.write_text("x")
    run_main([], env={"DB_PATH": str(db)})
    assert db.exists()
    code, out = run_main(["--reset-history"], env={"DB_PATH": str(db)})
    assert code == 0 and not db.exists() and "Deleted" in out


# ------------------------------------------------------------------ GIF validation
def make_gif(width=960, height=540, delays=(10,) * 12, gct=True):
    data = b"GIF89a" + struct.pack("<HHBBB", width, height, 0x80 if gct else 0, 0, 0)
    if gct:
        data += b"\x00\x00\x00\xff\xff\xff"
    for d in delays:
        data += b"\x21\xf9\x04\x00" + struct.pack("<H", d) + b"\x00\x00"
        data += b"\x2c" + struct.pack("<HHHH", 0, 0, width, height) + b"\x00" + b"\x02" + b"\x02\x44\x01" + b"\x00"
    return data + b"\x3b"


def test_gif_parser_reads_dimensions_frames_and_duration(tmp_path):
    p = tmp_path / "d.gif"
    p.write_bytes(make_gif(960, 540, delays=(8,) * 300))
    info = GM.inspect_gif(p)
    assert (info["width"], info["height"], info["frames"], info["duration_s"]) == (960, 540, 300, 24.0)
    p.write_bytes(make_gif(800, 450, delays=(0, 0, 100), gct=False))
    info = GM.inspect_gif(p)
    assert info["frames"] == 3 and info["duration_s"] == 1.2                       # a zero delay counts as 0.1 s, like browsers do
    assert GM.inspect_gif(tmp_path / "missing.gif") is None
    p.write_bytes(b"GIF89a" + b"\x00" * 5)
    assert GM.inspect_gif(p) is None
    p.write_bytes(b"not a gif at all")
    assert GM.inspect_gif(p) is None
    p.write_bytes(make_gif()[:60])
    assert GM.inspect_gif(p) is None or GM.inspect_gif(p)["frames"] < 12


def test_gif_validation_rules():
    ok = {"width": 960, "height": 540, "frames": 300, "duration_s": 60.0, "size_mb": 5.0}
    assert GM.validate(ok) == ([], [])
    errors, _ = GM.validate(dict(ok, width=400))
    assert any("too small" in e for e in errors)
    assert any("only 3 frame" in e for e in GM.validate(dict(ok, frames=3))[0])
    assert any("too large" in e for e in GM.validate(dict(ok, size_mb=20))[0])
    assert any("too long" in e for e in GM.validate(dict(ok, duration_s=120))[0])
    assert GM.validate(dict(ok, size_mb=9)) == ([], ["9 MB loads slowly on GitHub: aim for under 8 MB"])
    assert GM.validate(dict(ok, duration_s=10))[1] and GM.validate(dict(ok, width=1920))[1]
    assert GM.validate(None)[0] == ["not a valid GIF file"]


def test_gif_markdown_is_printed_only_for_a_valid_recording(tmp_path):
    def run(path):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = GM.main([str(path)])
        return code, buf.getvalue()
    code, out = run(tmp_path / "none.gif")
    assert code == 1 and "nothing was linked" in out and "![" not in out
    junk = tmp_path / "junk.gif"
    junk.write_bytes(b"fake")
    code, out = run(junk)
    assert code == 1 and "ERROR" in out and "![" not in out
    tiny = tmp_path / "tiny.gif"
    tiny.write_bytes(make_gif(960, 540, delays=(5,) * 3))
    code, out = run(tiny)
    assert code == 1 and "only 3 frame" in out and "![" not in out
    good = tmp_path / "good.gif"
    good.write_bytes(make_gif(960, 540, delays=(20,) * 300))
    code, out = run(good)
    assert code == 0 and "![Demo of the analyzer](good.gif)" in out and "960x540, 300 frames, 60.0 s" in out
    default = GM.DEFAULT
    assert not default.exists(), "the repository must not ship a placeholder GIF"
