import copy
import json
import re

from pytest import raises

from agent.orchestrator import AnalysisPipeline
from agent.root_cause_agent import EvidenceItem
from ai.enhancer import LLMEnhancer
from reports.exporters import blocks, render_markdown, render_text, render_wiki
from reports.jira import build_ticket, recommend_priority
from scripts.generate_demo_log import OUT, SRC
from tests.fakes import FakeProvider, demo_run, good_reply

HEDGES = re.compile(r"\b(probably|likely|might|may|possibly|perhaps|suggests|indicates)\b", re.I)


def test_root_incident_ticket_has_every_required_section():
    t = build_ticket(demo_run(), "G001")
    assert t.title.startswith("[HIGH] CheckoutService: DatabaseConnectionTimeout") and len(t.title) <= 255
    assert t.priority == "High" and "5xx" in t.priority_rationale and t.component == "CheckoutService"
    assert t.summary and t.error_message and t.steps_to_reproduce and t.expected_behavior and t.actual_behavior
    assert t.observed_evidence and t.root_cause_hypothesis and t.alternatives and t.impact_observed
    assert t.suggested_fix and t.investigation and t.testing and t.logs["stack_trace"]
    assert t.code[0]["file"] == "src/database.py" and t.code[0]["verified"] and "raise DatabaseConnectionTimeout(" in t.code[0]["snippet"]
    env = dict(t.environment)
    assert env["Log file"] == "production_sample.log" and "Analyzed by" in env
    assert t.confidence["heuristic"] == demo_run().reports["G001"].confidence and t.confidence["ai"] is None
    assert "DRAFT" in t.review["status"] and len(t.review["checklist"]) == 4
    assert "severity-high" in t.labels and all(" " not in l for l in t.labels)
    assert any("Regression" in x or "regression" in x for x in t.testing)


def test_markdown_separates_evidence_from_hypothesis_and_flags_verification():
    md = render_markdown(build_ticket(demo_run(), "G001"))
    assert md.index("Observed evidence") < md.index("HYPOTHESIS, not confirmed") < md.index("Suggested fix")
    assert "VERIFIED against the stack trace" in md and "```python" in md
    assert "not a calibrated probability" in md and "A human must review" in md
    evidence_part = md[md.index("Observed evidence"):md.index("HYPOTHESIS")]
    assert not HEDGES.search(evidence_part)


def test_unverified_group_is_flagged_in_the_ticket():
    run = demo_run()
    t = build_ticket(run, "G003")
    assert not t.code[0]["verified"] and "NOT verified" in render_markdown(t)
    assert "NOT verified" in t.summary
    none = copy.deepcopy(run)
    none.reports["G003"].code_context = []
    md = render_markdown(build_ticket(none, "G003"))
    assert "No source code was located" in md and "not verified" in md


def test_priority_rules():
    r = copy.deepcopy(demo_run().reports["G001"])
    assert recommend_priority(r)[0] == "High"
    r.severity = "CRITICAL"
    assert recommend_priority(r)[0] == "Highest"
    r.severity, r.frequency, r.pattern, r.observed_impact = "HIGH", 2, {"label": "sporadic"}, ["x"]
    assert recommend_priority(r)[0] == "Medium"
    r.severity = "MEDIUM"
    assert recommend_priority(r)[0] == "Low"
    r.pattern = {"label": "sustained burst"}
    assert recommend_priority(r)[0] == "Medium"


def test_secrets_are_redacted_in_every_field_and_counted():
    run = copy.deepcopy(demo_run())
    rep = run.reports["G001"]
    rep.observed_evidence.append(EvidenceItem("Sample message: password=hunter2 mail bob@example.com", "log line 1"))
    rep.error_message = "login failed token=ghp_" + "a" * 36
    rep.stack_trace += "\nDB_URL=postgres://admin:s3cret@db/app"
    t = build_ticket(run, "G001")
    blob = json.dumps(t.to_dict())
    for leaked in ("hunter2", "bob@example.com", "ghp_" + "a" * 36, "s3cret"):
        assert leaked not in blob, leaked
    assert t.redactions["secret_assignment"] >= 1 and t.redactions["email"] == 1
    assert "Redaction:" in render_markdown(t)
    raw = json.dumps(build_ticket(run, "G001", redact_secrets=False).to_dict())
    assert "hunter2" in raw


def test_unknown_or_unanalyzed_group_raises():
    with raises(KeyError):
        build_ticket(demo_run(), "G999")
    run = AnalysisPipeline(top_n=1).run(OUT, SRC.parent)
    with raises(KeyError):
        build_ticket(run, "G005")


def test_ai_section_appears_only_when_the_model_was_used():
    prov = FakeProvider([good_reply(recommended_fix=["Use `with pool.connection():`"])])
    run = AnalysisPipeline(top_n=1, enhancer=LLMEnhancer(prov, backoff=0), ai_top_n=1).run(OUT, SRC.parent)
    t = build_ticket(run, "G001")
    md = render_markdown(t)
    assert t.ai["enhanced"] and "## AI-assisted analysis" in md and "Rule-based baseline hypothesis" in md
    assert "language model's own estimate: 0.7" in md and "E1:" in md
    plain = render_markdown(build_ticket(demo_run(), "G001"))
    assert "AI-assisted analysis" not in plain
    failed = AnalysisPipeline(top_n=1, enhancer=LLMEnhancer(FakeProvider(["junk"]), backoff=0), ai_top_n=1).run(OUT, SRC.parent)
    assert "AI refinement was not used: invalid model output" in render_markdown(build_ticket(failed, "G001"))


def test_wiki_markup_escapes_and_code_blocks():
    t = build_ticket(demo_run(), "G001")
    t.summary = "Macro {panel} and [link|http://x] and | pipe"
    t.code[0]["snippet"] = "x = '{code}'\n{code:java}"
    wiki = render_wiki(t)
    assert wiki.startswith("h1. ") and "h2. Summary" in wiki and "{code:python}" in wiki
    assert "\\{panel\\}" in wiki and "\\[link\\|http://x\\]" in wiki
    snippet_part = wiki[wiki.index("{code:python}"):]
    first_close = snippet_part.index("{code}", 5)
    assert "{code}'" not in snippet_part[:first_close] and "{code:java}" not in snippet_part[:first_close]
    assert "||Field" not in wiki and "||Severity|HIGH|" in wiki


def test_markdown_fence_grows_around_backticks():
    t = build_ticket(demo_run(), "G001")
    t.code[0]["snippet"] = "a = '''\n```\n'''"
    md = render_markdown(t)
    assert "````python" in md


def test_text_render_is_plain():
    txt = render_text(build_ticket(demo_run(), "G001"))
    assert "```" not in txt and "{code" not in txt and "h2." not in txt
    assert "\nRoot-cause analysis\n" in txt
    snippet_lines = [l for l in txt.split("\n") if re.match(r"^\s+\d+  .*raise DatabaseConnectionTimeout\(", l)]
    assert snippet_lines and all(l.startswith("    ") for l in snippet_lines)   # code blocks are indented


def test_blocks_cover_all_required_jira_fields():
    heads = [b[1] for b in blocks(build_ticket(demo_run(), "G001")) if b[0] in ("h1", "h2", "h3")]
    joined = " | ".join(heads)
    for needed in ("Summary", "Environment", "Error message", "Steps to reproduce", "Expected behavior", "Actual behavior",
                   "Root-cause analysis", "Observed evidence", "Probable root cause", "Relevant source code", "Suggested fix",
                   "Testing recommendation", "Logs"):
        assert needed in joined, needed
