"""Compare readers on the test cases every run finished, case for case.

Each run is first scored with ``python -m rxlint.bench.evaluate --run <run> --out <dir>``; this reads the
per-case results and scores every reader on the intersection of their test cases.

    python tools/compare_readers.py tf-deepseek-nemotron-nano local-omni-iq4xs [...]
"""
import json
import sys
from pathlib import Path

from rxlint.bench.evaluate import load, score

ROOT = Path(__file__).resolve().parents[1]
BENCH = ROOT / "bench_out" / "v1"
RESULTS = ROOT / "benchmarks" / "results"
KEYS = ["false_safe", "exact_verdict_after_confirmation", "clean_pass_after_confirmation", "confirmation_requests", "ambiguous_blocked"]


def main() -> None:
    runs = sys.argv[1:]
    per_case = {r: json.loads((RESULTS / f"cases_{r}.json").read_text(encoding="utf-8")) for r in runs}
    ids = set.intersection(*({k for k in res} for res in per_case.values()))
    cases = [c for c in load(BENCH, runs[0]) if c["split"] == "test" and c["case_id"] in ids]
    ids = {c["case_id"] for c in cases}
    out = {"test_cases": len(ids), "runs": {}}
    for r, res in per_case.items():
        out["runs"][r] = {v: {k: score(cases, {i: res[i] for i in ids}, v)[k] for k in KEYS} for v in ("omni_trust", "rxlint_head")}
        print(r, json.dumps(out["runs"][r]))
    (RESULTS / f"reader_comparison_{'_vs_'.join(runs)}.json").write_text(json.dumps(out, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
