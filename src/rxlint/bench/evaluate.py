"""RxLintBench evaluation: perception, the reliability head, and end-to-end verdicts.

    python -m rxlint.bench.evaluate --bench bench_out/v1 --run local-omni-iq4xs [--train-head]

Variants scored on the same cases:

* ``oracle``        gold facts straight into the kernel (checks the rule oracle, perception excluded)
* ``omni_trust``    Nano Omni readings accepted as read (no second reader)
* ``rxlint_strict`` Nano Omni + OCR corroboration (P-PERC-02)
* ``rxlint_head``   reader + OCR + calibrated reliability head as a second gate (P-PERC-03)
* ``ocr_rules``     OCR engine + regex field parser + the same kernel (no generative model)

For every variant the case may end CANNOT_VERIFY with a confirmation request. The
``after_confirmation`` columns simulate the pharmacist typing the value as written, which is
what the product asks for; an overwritten dose has no single written value and stays blocked.
"""

from __future__ import annotations

import argparse
import json
import random
import re
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from ..core import EvidenceKind, Normalizer, Observation, SnapshotBuilder, load_pack, verify
from ..core.units import Unparseable, parse_frequency
from ..perception import reliability, grounding, refine
from ..perception.grounding import CORROBORATION_REQUIRED, OcrLine, ground

ROOT = Path(__file__).resolve().parents[3]
PACK = load_pack()
N = Normalizer(PACK)
SCORED = [f for f in reliability.FIELDS if f not in ("rx.route",)]


def load(bench: Path, run: str) -> list[dict[str, Any]]:
    cases = [json.loads(l) for l in (bench / "cases.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    out = []
    for c in cases:
        p = bench / "extractions" / run / f"{c['case_id']}.json"
        if p.exists():
            c["run"] = json.loads(p.read_text(encoding="utf-8"))
            if c["run"].get("case_id") != c["case_id"]:
                raise ValueError(f"extraction case id does not match manifest: {p}")
            out.append(c)
    return out


def require_complete_folds(cases: list[dict], manifest: list[dict], folds: tuple[str, ...]) -> None:
    for fold in folds:
        expected = {c["case_id"] for c in manifest if c["split"] == fold}
        actual = {c["case_id"] for c in cases if c["split"] == fold}
        if not expected or actual != expected:
            raise ValueError(f"{fold} fold incomplete: {len(actual)}/{len(expected)} cases; resume extraction before publishing or calibration")


def gold_map(c: dict[str, Any], name: str) -> dict[str, str]:
    return {g["field"]: g["raw"] for g in c["gold_rx" if name == "rx" else "gold_label"]}


BENCH_DIR: Path | None = None


def _ocr(c: dict[str, Any], name: str) -> list[OcrLine]:
    """OCR lines for a benchmark image, recomputed with the current engine and cached next to the image."""
    from ..perception.grounding import ocr_lines

    rec = c["run"]["images"][name]
    if rec.get("ocr_fingerprint") == grounding.fingerprint():
        return [OcrLine(**l) for l in rec["ocr"]]

    cache = BENCH_DIR / "ocr_cache" / grounding.fingerprint() / f"{c['case_id']}_{name}.json"
    if cache.exists():
        return [OcrLine(**l) for l in json.loads(cache.read_text(encoding="utf-8"))]
    lines = ocr_lines((BENCH_DIR / f"{c['case_id']}_{name}.jpg").read_bytes())
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps([l.__dict__ for l in lines]), encoding="utf-8")
    return lines


def regrounded(c: dict[str, Any], name: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rec = c["run"]["images"][name]
    if rec.get("refinement_version") == refine.VERSION and rec.get("ocr_fingerprint") == grounding.fingerprint():
        lines = [OcrLine(**l) for l in rec["ocr"]]
        doc = {"legibility": rec["extraction"].get("legibility", "good"),
               "ocr_mean": float(np.mean([l.score for l in lines])) if lines else 0.0}
        obs = refine.validate_products([dict(o) for o in rec["grounded"]], rec["extraction"].get("transcript", []),
            "prescription" if name == "rx" else "medicine")
        return obs, doc
    lines = _ocr(c, name)
    image = (BENCH_DIR / f"{c['case_id']}_{name}.jpg").read_bytes()
    kind = "prescription" if name == "rx" else "medicine"
    obs = refine.validate(ground(refine.recover(rec["extraction"]["observations"], lines, kind), lines, image))
    obs = refine.validate_products(obs, rec["extraction"].get("transcript", []), kind)
    doc = {"legibility": rec["extraction"].get("legibility", "good"),
           "ocr_mean": float(np.mean([l.score for l in lines])) if lines else 0.0}
    return obs, doc


def label(field: str, text: str, gold: dict[str, str]) -> int | None:
    if field not in gold:
        return None
    g = gold[field]
    if "|" in g:  # an overwritten value has no single correct reading
        return 0
    a, b = reliability.canonical(field, text, N), reliability.canonical(field, g, N)
    if b is None:
        return None
    return int(a is not None and a == b)


# ----------------------------------------------------------------------------- reliability dataset and head
def dataset(cases: list[dict[str, Any]], bench: Path) -> list[dict[str, Any]]:
    rows = []
    for c in cases:
        for name, kind in (("rx", "prescription"), ("label", "medicine")):
            obs, doc = regrounded(c, name)
            stats = reliability.ImageStats((bench / f"{c['case_id']}_{name}.jpg").read_bytes())
            gold = gold_map(c, name)
            for o in obs:
                y = label(o["field"], o["text"], gold)
                if y is None:
                    continue
                f = reliability.features(o, kind, doc, stats, N)
                rows.append({"case_id": c["case_id"], "split": c["split"], "field": o["field"], "y": y, "x": f,
                             "corroboration": o.get("corroboration"), "handwritten": c["handwritten"]})
    return rows


def select_threshold(probabilities: np.ndarray, correct: np.ndarray, max_false_accept: int = 0) -> tuple[float, dict[str, int]]:
    """Minimize correct-reading referrals under a VALIDATION-only false-accept budget.

    Scores at the threshold are accepted, so nextafter handles tied scores and a wrong reading
    scored at 1.0. No test labels or case-level verdicts participate in this choice.
    """
    if max_false_accept < 0 or len(probabilities) != len(correct) or not len(correct):
        raise ValueError("threshold selection requires validation readings and a nonnegative budget")
    if not np.isfinite(probabilities).all():
        raise ValueError("nonfinite reliability probabilities")
    candidates = [0.0, *[float(np.nextafter(p, np.inf)) for p in np.unique(probabilities)]]
    options = []
    for threshold in candidates:
        accepted = probabilities >= threshold
        wrong = int((accepted & (correct == 0)).sum())
        if wrong <= max_false_accept:
            accepted_correct = int((accepted & (correct == 1)).sum())
            options.append((accepted_correct, -wrong, threshold))
    _, _, threshold = max(options)
    accepted = probabilities >= threshold
    return threshold, {"accepted_correct": int((accepted & (correct == 1)).sum()),
                       "false_accepts": int((accepted & (correct == 0)).sum()),
                       "correct_readings_referred": int((~accepted & (correct == 1)).sum()),
                       "validation_corroborated_readings": len(correct)}


def train_head(rows: list[dict[str, Any]], max_val_false_accept: int = 0) -> dict[str, Any]:
    import lightgbm as lgb
    from sklearn.isotonic import IsotonicRegression
    from sklearn.metrics import roc_auc_score

    feats = reliability.FEATURES
    X = lambda rs: np.array([[r["x"][k] for k in feats] for r in rs], dtype=np.float32)
    y = lambda rs: np.array([r["y"] for r in rs])
    tr = [r for r in rows if r["split"] == "train"]
    va = [r for r in rows if r["split"] == "val"]
    te = [r for r in rows if r["split"] == "test"]
    if not tr or not va or len(set(y(tr))) < 2:
        raise ValueError("training requires train/validation folds and both label classes in training")
    params = dict(objective="binary", learning_rate=0.05, num_leaves=15, min_data_in_leaf=10, feature_fraction=0.8,
                  bagging_fraction=0.8, bagging_freq=1, lambda_l2=1.0, verbose=-1, seed=7, num_threads=2)
    booster = lgb.train(params, lgb.Dataset(X(tr), y(tr)), num_boost_round=300)
    iso = IsotonicRegression(out_of_bounds="clip", y_min=0, y_max=1).fit(booster.predict(X(va)), y(va))
    grid = np.linspace(0, 1, 101)
    calib = {"x": grid.tolist(), "y": iso.predict(grid).tolist()}
    meta = {"features": feats, "calibration": calib}

    def cal(rs):
        return np.interp(booster.predict(X(rs)), grid, calib["y"])

    # Minimize workflow friction subject to the specified validation false-accept budget.
    hv = [r for r in va if r["field"] in CORROBORATION_REQUIRED and r["corroboration"] == "corroborated"]
    pv = cal(hv)
    thr, selection = select_threshold(pv, y(hv), max_val_false_accept)
    meta["threshold"] = thr
    meta["trained_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    meta["selection"] = {"fold": "val", "objective": "minimize_correct_reading_referrals",
                         "max_false_accepts": max_val_false_accept, **selection}
    meta["ocr_fingerprint"] = grounding.fingerprint()
    meta["fold_readings"] = {"train": len(tr), "val": len(va)}

    report = head_metrics(rows, booster, meta)
    return {"booster": booster, "meta": meta, "report": report}


def head_metrics(rows: list[dict[str, Any]], booster: Any, meta: dict[str, Any]) -> dict[str, Any]:
    """Measure a frozen head on each fold without fitting or selecting from test labels."""
    from sklearn.metrics import roc_auc_score
    def y(rs):
        return np.array([r["y"] for r in rs])
    def cal(rs):
        X = np.array([[r["x"][k] for k in meta["features"]] for r in rs], dtype=np.float32)
        return reliability.calibrate(booster.predict(X, num_threads=2), meta)
    thr = meta["threshold"]
    report = {"threshold": thr, **{f"n_{s}": sum(r["split"] == s for r in rows) for s in ("train", "val", "test")},
              "selection": meta.get("selection", {})}
    va = [r for r in rows if r["split"] == "val"]
    te = [r for r in rows if r["split"] == "test"]
    for name, rs in (("val", va), ("test", te)):
        if len(set(y(rs))) > 1:
            report[f"auc_{name}"] = round(float(roc_auc_score(y(rs), cal(rs))), 4)
            report[f"auc_{name}_model_confidence"] = round(float(roc_auc_score(y(rs), [r["x"]["confidence"] for r in rs])), 4)
        hr = [r for r in rs if r["field"] in CORROBORATION_REQUIRED]
        if hr:
            p = cal(hr)
            yy = y(hr)
            strict = np.array([r["corroboration"] == "corroborated" for r in hr])
            head = strict & (p >= thr)
            cor = [i for i, r in enumerate(hr) if r["corroboration"] == "corroborated"]
            if len(set(yy[cor])) > 1:
                report[f"auc_{name}_corroborated"] = round(float(roc_auc_score(yy[cor], p[cor])), 4)
            for tag, acc in (("strict", strict), ("head", head)):
                report[f"{name}_{tag}_accept_rate"] = round(float(acc.mean()), 4)
                report[f"{name}_{tag}_false_accept"] = int((acc & (yy == 0)).sum())
                report[f"{name}_{tag}_false_accept_rate"] = round(float((acc & (yy == 0)).sum() / len(hr)), 4)
            report[f"{name}_high_risk_readings"] = len(hr)
            report[f"{name}_high_risk_wrong"] = int((yy == 0).sum())
    imp = booster.feature_importance("gain")
    report["top_features"] = [f for f, _ in sorted(zip(meta["features"], imp), key=lambda t: -t[1])[:8]]
    return report


# ----------------------------------------------------------------------------- OCR + rules baseline
def ocr_fields(lines: list[dict[str, Any]], kind: str) -> list[dict[str, Any]]:
    texts = [l["text"] for l in sorted(lines, key=lambda l: (round(l["bbox"][1], 2), l["bbox"][0]))]
    out: list[dict[str, Any]] = []

    def add(field, text):
        if text and not any(o["field"] == field for o in out):
            out.append({"field": field, "text": text.strip()})

    joined = " ".join(texts)
    for t in texts:
        if N.product(t).status == "exact":
            add("rx.drug" if kind == "prescription" else "dispensed.drug", t)
    if not any(o["field"].endswith(".drug") for o in out) and N.product(joined).status == "exact":
        add("rx.drug" if kind == "prescription" else "dispensed.drug", joined[:120])
    for t in texts:
        if re.search(r"\d\s*mg.*(/|per|pour)\s*\d*\s*ml", t, re.I):
            add("rx.strength" if kind == "prescription" else "dispensed.strength", re.search(r"\d.*ml", t, re.I).group(0))
    if kind == "prescription":
        for t in texts:
            m = re.search(r"(\d+[.,]?\d*)\s*kg\b", t, re.I)
            if m:
                add("rx.patient_weight", m.group(0))
            m = re.search(r"\b(\d+)\s*(months?|mois|years?|ans)\b", t, re.I)
            if m:
                add("rx.patient_age", m.group(0))
            if not re.search(r"mg", t, re.I):
                m = re.search(r"\b(\d+[.,]?\d*)\s*ml\b", t, re.I)
                if m:
                    add("rx.dose", m.group(0))
            try:
                parse_frequency(t)
                add("rx.frequency", t)
            except Unparseable:
                pass
            m = re.search(r"\b\d+\s*(days?|jours?)\b", t, re.I)
            if m:
                add("rx.duration", m.group(0))
            if N.indication(t).value:
                add("rx.indication", t)
    else:
        for t in texts:
            if re.search(r"\blot\b", t, re.I):
                add("dispensed.lot", t)
            if re.search(r"\bexp", t, re.I):
                add("dispensed.expiry", t)
            if re.search(r"\d+\s*ml.*(reconstitut|mixed|when)", t, re.I):
                add("dispensed.volume", re.search(r"\d+\s*ml.*", t, re.I).group(0))
    return out


# ----------------------------------------------------------------------------- end-to-end
def verdict(c: dict[str, Any], observations: list[tuple[dict[str, Any], str]], confirm: dict[str, str] | None = None) -> Any:
    b = SnapshotBuilder(N, c["case_id"])
    for o, asset in observations:
        b.add(Observation(field=o["field"], raw=o["text"], kind=EvidenceKind.VISUAL_OBSERVATION, asset_id=asset,
                          confidence=o.get("confidence"), legible=o.get("legible", True), alternatives=o.get("alternatives", []),
                          requires_confirmation=o.get("requires_confirmation", False), method=o.get("method", "model")))
    for k, v in c["patient"].items():
        b.add(Observation(field=k, raw=v, kind=EvidenceKind.USER_ENTERED_FACT, method="typed"))
    for k, v in (confirm or {}).items():
        b.add(Observation(field=k, raw=v, kind=EvidenceKind.USER_ENTERED_FACT, method="confirmation"))
    return verify(b.build(dispense_date=date.fromisoformat(c["dispense_date"])), PACK)


CONFIRM_FIELD = {"rx.dose": "rx.dose", "rx.strength": "rx.strength", "patient.weight_kg": "rx.patient_weight",
                 "dispensed.strength": "dispensed.strength", "rx.frequency": "rx.frequency", "rx.duration_days": "rx.duration",
                 "dispensed.expiry": "dispensed.expiry", "dispensed.product": "dispensed.drug", "rx.product": "rx.drug",
                 "patient.age_months": "rx.patient_age", "dispensed.volume_ml": "dispensed.volume", "rx.indication": "rx.indication",
                 "patient.allergies": "patient.allergies", "patient.current_medications": "patient.medications"}


def confirmation_for(c: dict[str, Any], v: Any) -> dict[str, str] | None:
    """What a pharmacist would type when asked: the value as written. None when no single value is written."""
    if v.state != "CANNOT_VERIFY" or not v.clarification:
        return None
    gold = {**gold_map(c, "rx"), **gold_map(c, "label"), **c["patient"]}
    out = {}
    for fact in v.clarification["fields"]:
        f = CONFIRM_FIELD.get(fact)
        if f is None or f not in gold:
            continue
        if "|" in gold[f]:
            return None
        key = "patient.weight" if f == "rx.patient_weight" else "patient.age" if f == "rx.patient_age" else f
        out[key] = gold[f]
    return out or None


def case_variants(c: dict[str, Any], bench: Path, use_head: bool) -> dict[str, Any]:
    res: dict[str, Any] = {}
    obs_by = {}
    for name, kind in (("rx", "prescription"), ("label", "medicine")):
        obs, doc = regrounded(c, name)
        obs_by[name] = (obs, doc, kind)

    def run(tag: str, obs: list[tuple[dict[str, Any], str]]):
        v = verdict(c, obs)
        conf: dict[str, str] = {}
        v2 = v
        for _ in range(3):  # the pharmacist answers each request with the value as written
            more = confirmation_for(c, v2)
            if not more or all(conf.get(k) == x for k, x in more.items()):
                break
            conf.update(more)
            v2 = verdict(c, obs, conf)
        res[tag] = {"state": v.state, "after": v2.state, "asked": v.state == "CANNOT_VERIFY", "confirmed": sorted(conf),
                    "fails": [f.rule_id for f in v.findings if f.status == "fail" and f.severity != "advisory"]}

    # gold oracle
    gold_obs = []
    for name in ("rx", "label"):
        for g in c["gold_rx" if name == "rx" else "gold_label"]:
            if "|" in g["raw"]:
                a, b = g["raw"].split(" | ")
                gold_obs.append(({"field": g["field"], "text": a, "alternatives": [b]}, name))
            else:
                gold_obs.append(({"field": g["field"], "text": g["raw"]}, name))
    run("oracle", gold_obs)

    trust = [({**o, "requires_confirmation": False}, name)
             for name in ("rx", "label") for o in c["run"]["images"][name]["extraction"]["observations"]]
    # "trust" still keeps the model's own alternatives list: it is the model's reading, used as read.
    run("omni_trust", [({**o, "alternatives": []}, n) for o, n in trust])

    strict = []
    for n, (obs, _, _) in obs_by.items():
        strict += [(o, n) for o in obs]
        strict += [({"field": o["field"], "text": o["ocr_text"], "method": "rapidocr"}, n) for o in obs
                   if o["field"] in ("rx.drug", "dispensed.drug", "rx.indication") and o.get("grounding") == "ocr" and o.get("ocr_text")]
    run("rxlint_strict", strict)

    if use_head and reliability.load_head() is not None:
        head_obs = []
        for n, (obs, doc, kind) in obs_by.items():
            scored = reliability.apply([dict(o) for o in obs], kind, doc, (bench / f"{c['case_id']}_{n}.jpg").read_bytes(), N)
            head_obs += [(o, n) for o in scored]
            head_obs += [({"field": o["field"], "text": o["ocr_text"], "method": "rapidocr"}, n) for o in obs
                         if o["field"] in ("rx.drug", "dispensed.drug", "rx.indication") and o.get("grounding") == "ocr" and o.get("ocr_text")]
        run("rxlint_head", head_obs)

    ocr = []
    for name, kind in (("rx", "prescription"), ("label", "medicine")):
        ocr += [(o, name) for o in ocr_fields([l.__dict__ for l in _ocr(c, name)], kind)]
    run("ocr_rules", ocr)
    return res


def score(cases: list[dict[str, Any]], results: dict[str, dict[str, Any]], variant: str) -> dict[str, Any]:
    n = len(cases)
    err = [c for c in cases if c["expected_state"] != "PASS"]
    review = [c for c in cases if c["expected_state"] == "REVIEW"]
    clean = [c for c in cases if c["mutation"] == "NONE"]
    ambiguous = [c for c in cases if c["mutation"] == "AMBIGUOUS_HANDWRITING"]
    st = lambda c, k="state": results[c["case_id"]][variant][k]
    fs = sum(st(c) == "PASS" for c in err)
    fs_after = sum(st(c, "after") == "PASS" for c in err)
    out = {
        "cases": n,
        "false_safe": f"{fs}/{len(err)}",
        "false_safe_rate": round(fs / len(err), 4) if err else None,
        "false_safe_after_confirmation": f"{fs_after}/{len(err)}",
        "review_recall": round(sum(st(c) == "REVIEW" for c in review) / len(review), 4) if review else None,
        "review_recall_after_confirmation": round(sum(st(c, "after") == "REVIEW" for c in review) / len(review), 4) if review else None,
        "exact_verdict": round(sum(st(c) == c["expected_state"] for c in cases) / n, 4),
        "exact_verdict_after_confirmation": round(sum(st(c, "after") == c["expected_state"] for c in cases) / n, 4),
        "clean_pass_rate": round(sum(st(c) == "PASS" for c in clean) / len(clean), 4) if clean else None,
        "clean_pass_after_confirmation": round(sum(st(c, "after") == "PASS" for c in clean) / len(clean), 4) if clean else None,
        "confirmation_requests": round(sum(results[c["case_id"]][variant]["asked"] for c in cases) / n, 4),
        "ambiguous_blocked": f"{sum(st(c, 'after') == 'CANNOT_VERIFY' for c in ambiguous)}/{len(ambiguous)}",
    }
    return out


def perception_stats(cases: list[dict[str, Any]]) -> dict[str, Any]:
    per = defaultdict(lambda: [0, 0])
    halluc = 0
    total = 0
    for c in cases:
        for name in ("rx", "label"):
            gold = gold_map(c, name)
            for o in c["run"]["images"][name]["extraction"]["observations"]:
                if o["field"] == "rx.route":
                    continue
                total += 1
                y = label(o["field"], o["text"], gold)
                if o["field"] not in gold:
                    halluc += 1
                    continue
            for f in gold:
                if f not in SCORED or label(f, gold[f], gold) is None:
                    continue
                readings = [o for o in c["run"]["images"][name]["extraction"]["observations"] if o["field"] == f]
                per[f][0] += int(bool(readings) and all(label(f, o["text"], gold) == 1 for o in readings))
                per[f][1] += 1  # one denominator per case-field, including omissions
    fields = {f: round(a / b, 4) for f, (a, b) in sorted(per.items()) if b}
    return {"field_exact": fields, "field_counts": {f: {"exact": a, "total": b} for f, (a,b) in sorted(per.items())},
            "readings": total, "fields_not_in_gold": halluc}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bench", default=str(ROOT / "bench_out" / "v1"))
    ap.add_argument("--run", default="local-omni-iq4xs")
    ap.add_argument("--train-head", action="store_true")
    ap.add_argument("--max-val-false-accept", type=int, default=0)
    ap.add_argument("--model-dir", help="stage a new head separately from the deployed model")
    ap.add_argument("--no-summary", action="store_true", help="keep the product's published summary unchanged")
    ap.add_argument("--out", default=str(ROOT / "benchmarks" / "results"))
    args = ap.parse_args()
    global BENCH_DIR
    bench = Path(args.bench)
    BENCH_DIR = bench
    if args.model_dir:
        reliability.MODEL_DIR = Path(args.model_dir)
        reliability.load_head.cache_clear()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    cases = load(bench, args.run)
    manifest = [json.loads(l) for l in (bench / "cases.jsonl").read_text(encoding="utf8").splitlines() if l.strip()]
    if not cases:
        raise ValueError("no completed extractions")
    if args.train_head:
        require_complete_folds(cases, manifest, ("train", "val"))
    if not args.no_summary:
        require_complete_folds(cases, manifest, ("test",))
    print(f"{len(cases)} cases with extractions", Counter(c["split"] for c in cases))

    head_report = None
    if args.train_head:
        rows = dataset(cases, bench)
        print(f"reliability dataset: {len(rows)} readings", Counter(r["split"] for r in rows))
        h = train_head(rows, args.max_val_false_accept)
        reliability.MODEL_DIR.mkdir(parents=True, exist_ok=True)
        h["booster"].save_model(str(reliability.MODEL_DIR / "head.txt"))
        (reliability.MODEL_DIR / "head.json").write_text(json.dumps(h["meta"], indent=1), encoding="utf-8")
        reliability.load_head.cache_clear()
        head_report = h["report"]
        (out / "reliability_head.json").write_text(json.dumps(head_report, indent=1), encoding="utf-8")
        print(json.dumps(head_report, indent=1))
    elif reliability.load_head() is not None:
        booster, meta = reliability.load_head()
        head_report = head_metrics(dataset(cases, bench), booster, meta)

    results = {c["case_id"]: case_variants(c, bench, use_head=True) for c in cases}
    variants = ["oracle", "omni_trust", "rxlint_strict", "rxlint_head", "ocr_rules"]
    variants = [v for v in variants if all(v in results[c["case_id"]] for c in cases)]
    by_split = {}
    for split in ("train", "val", "test", "all"):
        cs = cases if split == "all" else [c for c in cases if c["split"] == split]
        if cs:
            by_split[split] = {v: score(cs, results, v) for v in variants}
    perc = {s: perception_stats([c for c in cases if s == "all" or c["split"] == s]) for s in ("test", "all")}
    full = {"run": args.run, "cases": len(cases), "scores": by_split, "perception": perc, "reliability_head": head_report,
            "fold_completeness": {s: {"completed": sum(c["split"] == s for c in cases), "expected": sum(c["split"] == s for c in manifest)} for s in ("train", "val", "test")},
            "ocr_fingerprint": grounding.fingerprint(), "refinement_version": refine.VERSION,
            "product_audit_version": refine.PRODUCT_AUDIT_VERSION,
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    (out / f"bench_{args.run}.json").write_text(json.dumps(full, indent=1), encoding="utf-8")
    (out / f"cases_{args.run}.json").write_text(json.dumps(results, indent=1), encoding="utf-8")
    if not args.no_summary:
        write_summary(full, out)
    for v in variants:
        print(v, json.dumps(by_split.get("test", by_split["all"])[v]))


def reader_name(run: str) -> str:
    if "omni" in run:
        return "Nemotron 3 Nano Omni"
    return ("Qwen 3.8 27B" if "qwen38" in run else "DeepSeek V4.1 Flash") + " + " + ("Nemotron 3.5 Lightning" if "lightning" in run else "Nemotron 3 Nano")


def names(reader: str) -> dict[str, str]:
    return {"oracle": "Kernel on gold facts", "omni_trust": f"{reader} readings trusted as read",
            "rxlint_strict": "RxLint: reader + OCR corroboration", "rxlint_head": "RxLint: + reliability head",
            "ocr_rules": "OCR + regex + same kernel"}


def write_summary(full: dict[str, Any], out: Path) -> None:
    reader = reader_name(full["run"])
    NAMES = names(reader)
    split = "test" if "test" in full["scores"] else "all"
    s = full["scores"][split]
    cols = ["System", "False-safe before confirmation", "False-safe after confirmation", "Review recall before confirmation", "Exact before confirmation", "Clean PASS before confirmation", "Asked to confirm", "Exact after confirmation"]
    rows = [{"System": NAMES[v], "False-safe before confirmation": m["false_safe"], "False-safe after confirmation": m["false_safe_after_confirmation"],
             "Review recall before confirmation": m["review_recall"], "Exact before confirmation": m["exact_verdict"], "Clean PASS before confirmation": m["clean_pass_rate"],
             "Asked to confirm": m["confirmation_requests"], "Exact after confirmation": m["exact_verdict_after_confirmation"]}
            for v, m in s.items()]
    best = s.get("rxlint_head") or s.get("rxlint_strict")
    trust = s["omni_trust"]
    # Presentation uses published reports only: no reader rerun or model fitting.
    headline = [
        {"label": "cases needing confirmation", "value": f"{best['confirmation_requests'] * 100:.1f}%",
         "note": f"{round(best['confirmation_requests'] * best['cases'])}/{best['cases']} cases; unresolved fields reviewed together"},
        {"label": "exact verdict after simulated confirmation", "value": f"{best['exact_verdict_after_confirmation'] * 100:.1f}%",
         "note": f"{trust['exact_verdict_after_confirmation'] * 100:.1f}% when readings are trusted as read"},
        {"label": "overwritten doses held for confirmation", "value": best["ambiguous_blocked"],
         "note": f"{trust['ambiguous_blocked']} when readings are trusted as read"},
    ]
    r = full.get("reliability_head")
    if r and f"{split}_head_false_accept" in r:
        headline.insert(0, {"label": "incorrect high-risk readings accepted", "value": str(r[f"{split}_head_false_accept"]),
                            "note": f"{r[f'{split}_high_risk_readings']} high-risk readings evaluated"})
    else:
        headline.insert(0, {"label": f"false-safe cases, RxLint ({split} fold)", "value": best["false_safe"],
                            "note": f"error cases returned as PASS; {trust['false_safe']} when readings are trusted as read"})
    tables = []
    tables.append({"title": f"End-to-end verdicts, {split} fold ({s['oracle']['cases']} cases)",
                   "note": "False-safe means an error case returned PASS. Confirmation is simulated from written ground truth. Gold facts are an upper bound.", "columns": cols, "rows": rows})
    pf = full["perception"].get(split) or full["perception"]["all"]
    tables.append({"title": f"{reader} field accuracy (exact after RxLint parsing)", "columns": ["Field", "Exact"],
                   "rows": [{"Field": k, "Exact": v} for k, v in pf["field_exact"].items()]})
    if full.get("reliability_head"):
        r = full["reliability_head"]
        conf = any(r.get(f"auc_{f}_model_confidence") not in (None, 0.5) for f in ("val", "test"))
        tables.append({"title": "Reliability head on high-risk readings", "note": f"threshold {r['threshold']:.3f} set on validation; the head only adds confirmations and never waives OCR corroboration",
                       "columns": ["Fold", "Readings", "Wrong readings", "Accepted, OCR rule", "False accepts, OCR rule", "Accepted, OCR rule + head", "False accepts, OCR rule + head", "AUC head", "AUC head on corroborated"]
                       + (["AUC model confidence"] if conf else []),
                       "rows": [{"Fold": f, "Readings": r.get(f"{f}_high_risk_readings"), "Wrong readings": r.get(f"{f}_high_risk_wrong"),
                                 "Accepted, OCR rule": r.get(f"{f}_strict_accept_rate"), "False accepts, OCR rule": r.get(f"{f}_strict_false_accept"),
                                 "Accepted, OCR rule + head": r.get(f"{f}_head_accept_rate"), "False accepts, OCR rule + head": r.get(f"{f}_head_false_accept"),
                                 "AUC head": r.get(f"auc_{f}"), "AUC head on corroborated": r.get(f"auc_{f}_corroborated"),
                                 "AUC model confidence": r.get(f"auc_{f}_model_confidence")} for f in ("val", "test")]})
    summary = {"status": "ok", "generated_at": full["generated_at"], "headline": headline, "tables": tables,
               "description": f"{full['cases']} rendered cases; train/validation/test folds kept separate. Perception by {reader}; every verdict by the deterministic kernel."}
    (out / "summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
