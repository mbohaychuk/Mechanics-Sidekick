# evals/diff.py
"""Compare two eval result files and surface regressions, gains, and pass-rate deltas.

Used as a library function (compare_results) and as a CLI:
    uv run python -m evals.diff baseline.json candidate.json
"""
import argparse
import json
import sys
from collections import defaultdict


def compare_results(baseline: dict, candidate: dict) -> dict:
    base_by_id = {r["id"]: r for r in baseline["records"]}
    cand_by_id = {r["id"]: r for r in candidate["records"]}

    common_ids = set(base_by_id) & set(cand_by_id)
    only_baseline = sorted(set(base_by_id) - set(cand_by_id))
    only_candidate = sorted(set(cand_by_id) - set(base_by_id))

    regressed = []
    newly_passing = []
    unchanged = []
    for entry_id in sorted(common_ids):
        b = base_by_id[entry_id]
        c = cand_by_id[entry_id]
        summary = {"id": entry_id, "failure_mode": c["failure_mode"]}
        if b["passed"] and not c["passed"]:
            regressed.append(summary)
        elif not b["passed"] and c["passed"]:
            newly_passing.append(summary)
        else:
            unchanged.append({**summary, "passed": c["passed"]})

    pass_rate_delta = _pass_rate_delta_per_mode(baseline, candidate)

    return {
        "regressed": regressed,
        "newly_passing": newly_passing,
        "unchanged": unchanged,
        "only_in_baseline": [
            {"id": i, "failure_mode": base_by_id[i]["failure_mode"]} for i in only_baseline
        ],
        "only_in_candidate": [
            {"id": i, "failure_mode": cand_by_id[i]["failure_mode"]} for i in only_candidate
        ],
        "pass_rate_delta": pass_rate_delta,
    }


def _pass_rate_delta_per_mode(baseline: dict, candidate: dict) -> dict[str, float]:
    """Per failure_mode: candidate_pass_rate - baseline_pass_rate."""
    def rates(records):
        groups: dict[str, list[bool]] = defaultdict(list)
        for r in records:
            groups[r["failure_mode"]].append(r["passed"])
        return {mode: sum(passes) / len(passes) for mode, passes in groups.items()}

    base_rates = rates(baseline["records"])
    cand_rates = rates(candidate["records"])
    modes = set(base_rates) | set(cand_rates)
    return {m: cand_rates.get(m, 0.0) - base_rates.get(m, 0.0) for m in sorted(modes)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Diff two eval result files.")
    parser.add_argument("baseline", help="Path to baseline result JSON.")
    parser.add_argument("candidate", help="Path to candidate result JSON.")
    args = parser.parse_args(argv)

    with open(args.baseline) as f:
        baseline = json.load(f)
    with open(args.candidate) as f:
        candidate = json.load(f)

    diff = compare_results(baseline, candidate)
    print(json.dumps(diff, indent=2))
    return 1 if diff["regressed"] else 0


if __name__ == "__main__":
    sys.exit(main())
