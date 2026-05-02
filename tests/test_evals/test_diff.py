# tests/test_evals/test_diff.py
from evals.diff import compare_results


def test_compare_results_lists_regressions_and_new_passes():
    baseline = {
        "records": [
            {"id": "a", "failure_mode": "x", "passed": True},
            {"id": "b", "failure_mode": "x", "passed": False},
            {"id": "c", "failure_mode": "y", "passed": True},
        ],
    }
    candidate = {
        "records": [
            {"id": "a", "failure_mode": "x", "passed": False},
            {"id": "b", "failure_mode": "x", "passed": True},
            {"id": "c", "failure_mode": "y", "passed": True},
        ],
    }
    diff = compare_results(baseline, candidate)

    assert diff["regressed"] == [{"id": "a", "failure_mode": "x"}]
    assert diff["newly_passing"] == [{"id": "b", "failure_mode": "x"}]
    assert diff["unchanged"] == [{"id": "c", "failure_mode": "y", "passed": True}]


def test_compare_results_pass_rate_delta_per_failure_mode():
    baseline = {
        "records": [
            {"id": "a1", "failure_mode": "table_spec", "passed": False},
            {"id": "a2", "failure_mode": "table_spec", "passed": True},
        ],
    }
    candidate = {
        "records": [
            {"id": "a1", "failure_mode": "table_spec", "passed": True},
            {"id": "a2", "failure_mode": "table_spec", "passed": True},
        ],
    }
    diff = compare_results(baseline, candidate)
    assert diff["pass_rate_delta"]["table_spec"] == 0.5


def test_compare_results_handles_entry_added_only_in_candidate():
    baseline = {"records": [{"id": "a", "failure_mode": "x", "passed": True}]}
    candidate = {
        "records": [
            {"id": "a", "failure_mode": "x", "passed": True},
            {"id": "b", "failure_mode": "x", "passed": True},
        ],
    }
    diff = compare_results(baseline, candidate)
    assert diff["only_in_candidate"] == [{"id": "b", "failure_mode": "x"}]


def test_compare_results_handles_entry_dropped_from_candidate():
    baseline = {
        "records": [
            {"id": "a", "failure_mode": "x", "passed": True},
            {"id": "b", "failure_mode": "x", "passed": False},
        ],
    }
    candidate = {"records": [{"id": "a", "failure_mode": "x", "passed": True}]}
    diff = compare_results(baseline, candidate)
    assert diff["only_in_baseline"] == [{"id": "b", "failure_mode": "x"}]
