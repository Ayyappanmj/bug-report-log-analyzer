import pytest

pytest.importorskip("pydantic")
from pydantic import ValidationError

from ai.schemas import RootCauseAnalysis, Severity


def test_valid_analysis_defaults():
    a = RootCauseAnalysis(incident="x", severity="HIGH", confidence=0.5)
    assert a.severity is Severity.HIGH and a.generated_by == "deterministic-rules"


def test_confidence_out_of_range_rejected():
    with pytest.raises(ValidationError):
        RootCauseAnalysis(incident="x", severity="HIGH", confidence=1.5)


def test_invalid_severity_rejected():
    with pytest.raises(ValidationError):
        RootCauseAnalysis(incident="x", severity="BAD")


def test_evidence_and_inference_are_separate_fields():
    a = RootCauseAnalysis(incident="x", severity="LOW",
                          observed_evidence=[{"text": "47 timeouts", "source": "log lines 1-9"}],
                          probable_root_cause="pool saturation")
    assert a.observed_evidence[0].text == "47 timeouts" and a.probable_root_cause == "pool saturation"


def test_deterministic_report_validates_against_schema():
    from agent.orchestrator import AnalysisPipeline
    from scripts.generate_demo_log import OUT, SRC
    run = AnalysisPipeline(top_n=8).run(OUT, SRC.parent)
    assert run.reports
    for report in run.reports.values():
        parsed = RootCauseAnalysis.model_validate(report.to_dict())
        assert parsed.group_id == report.group_id and parsed.confidence == report.confidence
