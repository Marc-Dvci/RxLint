"""Does the kernel reach the verdict each mutation declares, on gold facts?

Generates RxLintBench cases with the benchmark's own generator (fresh seed, same fold recipes),
renders each document in memory to get its gold field text, feeds the gold facts straight into the
kernel exactly as the benchmark's ``oracle`` variant does, and compares the verdict with the state
and failing rule family the mutation declares. Nothing is written to disk except the report.

    python tools/oracle_check.py --train 750 --val 350 --test 600 --seed 2026
    python tools/oracle_check.py --manifest bench_out/v1/cases.jsonl   # re-check a rendered set
"""
import argparse
import json
import random
import time
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from rxlint.bench import evaluate
from rxlint.bench.generate import MUTATIONS, SPLITS, make_case
from rxlint.bench.render import LabelSpec, RxSpec, bottle_photo, document_photo, perturb, render_label, render_prescription

ROOT = Path(__file__).resolve().parents[1]
SETTLED = ("passed", "not_applicable")


def gold(c: dict) -> dict:
    """The gold boxes ``generate.render_case`` stores, without writing the photos."""
    rx_spec = RxSpec(**{k: v for k, v in c["rx"].items() if k in RxSpec.__dataclass_fields__})
    lab_spec = LabelSpec(**{k: (tuple(v) if k == "accent" else v) for k, v in c["label"].items() if k in LabelSpec.__dataclass_fields__})
    seed = int(c["case_id"][2:])
    c["gold_rx"] = perturb(document_photo(render_prescription(rx_spec), seed=seed), c["perturbation_rx"], seed=seed).gold()
    c["gold_label"] = perturb(bottle_photo(render_label(lab_spec), seed=seed + 1), c["perturbation_label"], seed=seed + 1).gold()
    return c


def generated(n_train: int, n_val: int, n_test: int, seed: int) -> list[dict]:
    # Every third case clean, as in generate.generate; the rest take all 16 error families in turn
    # (the frozen benchmark's schedule reaches eight of them).
    rng = random.Random(seed)
    muts = list(MUTATIONS)
    cases, i = [], 0
    for split, n in (("train", n_train), ("val", n_val), ("test", n_test)):
        cfg = SPLITS[split]
        for k in range(n):
            mutation = "NONE" if k % 3 == 0 else muts[1 + (k - k // 3 - 1) % (len(muts) - 1)]
            cases.append(gold(asdict(make_case(i, rng, split, cfg["products"], cfg["fonts"], cfg["perts"], mutation))))
            i += 1
    return cases


def check(c: dict) -> dict:
    obs = []
    for name in ("rx", "label"):
        for g in c["gold_rx" if name == "rx" else "gold_label"]:
            if "|" in g["raw"]:
                a, b = g["raw"].split(" | ")
                obs.append(({"field": g["field"], "text": a, "alternatives": [b]}, name))
            else:
                obs.append(({"field": g["field"], "text": g["raw"]}, name))
    v = evaluate.verdict(c, obs)
    raised = sorted({f.rule_id for f in v.findings if f.status not in SETTLED and f.severity != "advisory"})
    rule_ok = c["expected_rule"] is None or any(r.startswith(c["expected_rule"]) for r in raised)
    return {"case_id": c["case_id"], "split": c["split"], "mutation": c["mutation"], "expected_state": c["expected_state"],
            "state": v.state, "expected_rule": c["expected_rule"], "raised": raised,
            "state_ok": v.state == c["expected_state"], "rule_ok": rule_ok}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--train", type=int, default=750)
    ap.add_argument("--val", type=int, default=350)
    ap.add_argument("--test", type=int, default=600)
    ap.add_argument("--seed", type=int, default=2026)
    ap.add_argument("--manifest", help="re-check an already rendered manifest instead of generating")
    ap.add_argument("--out", default=str(ROOT / "benchmarks" / "results" / "oracle_agreement.json"))
    args = ap.parse_args()
    t0 = time.time()
    if args.manifest:
        cases = [json.loads(l) for l in Path(args.manifest).read_text(encoding="utf-8").splitlines() if l.strip()]
        source = {"manifest": Path(args.manifest).as_posix()}
    else:
        cases = generated(args.train, args.val, args.test, args.seed)
        source = {"generator": "rxlint.bench.generate.make_case", "seed": args.seed,
                  "folds": {"train": args.train, "val": args.val, "test": args.test}}
    rows = [check(c) for c in cases]
    agree = [r for r in rows if r["state_ok"] and r["rule_ok"]]
    by_mutation = {m: {"cases": n, "agree": sum(r["state_ok"] and r["rule_ok"] for r in rows if r["mutation"] == m)}
                   for m, n in sorted(Counter(r["mutation"] for r in rows).items())}
    report = {
        "cases": len(rows),
        "agree": len(agree),
        "verdict_agree": sum(r["state_ok"] for r in rows),
        "rule_family_agree": sum(r["rule_ok"] for r in rows),
        "by_split": {s: {"cases": n, "agree": sum(r["state_ok"] and r["rule_ok"] for r in rows if r["split"] == s)}
                     for s, n in Counter(r["split"] for r in rows).items()},
        "by_mutation": by_mutation,
        "disagreements": [r for r in rows if not (r["state_ok"] and r["rule_ok"])],
        "source": source,
        "rulepack_sha256": evaluate.PACK.sha256,
        "seconds": round(time.time() - t0, 1),
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    Path(args.out).write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("cases", "agree", "verdict_agree", "rule_family_agree", "by_split", "seconds")}, indent=1))
    if report["disagreements"]:
        print(json.dumps(report["disagreements"][:10], indent=1))


if __name__ == "__main__":
    main()
