# tests/test_evals/test_metrics.py
from evals.metrics import compute_metrics


def _record(
    *,
    id: str = "x",
    failure_mode: str = "general_procedure",
    passed: bool = True,
    iterations: int = 1,
    latency_s: float = 1.0,
    sources: list[dict] | None = None,
    expected_pdf: str | None = None,
    expected_pages: list[int] | None = None,
):
    return {
        "id": id,
        "failure_mode": failure_mode,
        "passed": passed,
        "iterations": iterations,
        "latency_s": latency_s,
        "sources": sources or [],
        "expected_source_pdf": expected_pdf,
        "expected_source_pages": expected_pages or [],
    }


def test_compute_metrics_overall_pass_at_1():
    records = [_record(passed=True), _record(passed=False), _record(passed=True)]
    m = compute_metrics(records)
    assert m["overall"]["pass_at_1"] == 2 / 3


def test_compute_metrics_per_failure_mode():
    records = [
        _record(failure_mode="table_spec", passed=True),
        _record(failure_mode="table_spec", passed=False),
        _record(failure_mode="negative", passed=True),
    ]
    m = compute_metrics(records)
    assert m["by_failure_mode"]["table_spec"]["pass_at_1"] == 0.5
    assert m["by_failure_mode"]["negative"]["pass_at_1"] == 1.0


def test_compute_metrics_source_page_precision_and_recall():
    """Precision: of returned (pdf, page) pairs, fraction that are expected.
    Recall: fraction of expected pages covered by returned sources."""
    records = [
        _record(
            sources=[{"filename": "manual.pdf", "page": 4}, {"filename": "manual.pdf", "page": 99}],
            expected_pdf="manual.pdf",
            expected_pages=[4, 5],
        ),
    ]
    m = compute_metrics(records)
    assert m["overall"]["source_page_precision"] == 0.5
    assert m["overall"]["source_page_recall"] == 0.5


def test_compute_metrics_skips_source_metrics_when_no_expectation():
    records = [_record(sources=[{"filename": "x.pdf", "page": 1}], expected_pdf=None)]
    m = compute_metrics(records)
    assert m["overall"]["source_page_precision"] is None
    assert m["overall"]["source_page_recall"] is None


def test_compute_metrics_mean_iterations_and_latency():
    records = [
        _record(iterations=1, latency_s=2.0),
        _record(iterations=3, latency_s=4.0),
    ]
    m = compute_metrics(records)
    assert m["overall"]["mean_iterations"] == 2.0
    assert m["overall"]["mean_latency_s"] == 3.0


def test_compute_metrics_handles_empty_input():
    m = compute_metrics([])
    assert m["overall"]["pass_at_1"] == 0.0
    assert m["overall"]["count"] == 0
    assert m["by_failure_mode"] == {}
