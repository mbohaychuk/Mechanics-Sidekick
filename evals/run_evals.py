# evals/run_evals.py
"""CLI entry-point: `uv run python -m evals.run_evals [--out FILE]`."""
import argparse
import json
import sys
from pathlib import Path

from evals.metrics import compute_metrics
from evals.runner import run


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the eval set against the current branch.")
    parser.add_argument(
        "--out", default=None,
        help="Output JSON path. Defaults to evals/results/<ts>-<sha>.json.",
    )
    parser.add_argument(
        "--eval-set", default="evals/eval_set.json",
        help="Path to eval_set.json.",
    )
    args = parser.parse_args(argv)

    output_path = run(eval_set_path=args.eval_set, output_path=args.out)
    payload = json.loads(Path(output_path).read_text())
    metrics = compute_metrics(payload["records"])

    print(f"\nResults written to: {output_path}\n")
    print(f"Overall pass@1: {metrics['overall']['pass_at_1']:.2%} "
          f"({metrics['overall']['count']} entries)")
    print(f"Mean iterations: {metrics['overall']['mean_iterations']:.2f}")
    print(f"Mean latency: {metrics['overall']['mean_latency_s']:.2f}s")
    if metrics['overall']['source_page_precision'] is not None:
        print(f"Source-page precision: {metrics['overall']['source_page_precision']:.2%}")
        print(f"Source-page recall: {metrics['overall']['source_page_recall']:.2%}")

    print("\nBy failure mode:")
    for mode, m in sorted(metrics["by_failure_mode"].items()):
        print(f"  {mode:24s}  pass@1 = {m['pass_at_1']:.0%}  ({m['count']} entries)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
