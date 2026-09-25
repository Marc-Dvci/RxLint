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
from ..perception import reliability
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
            out.append(c)
    return out


def gold_map(c: dict[str, Any], name: str) -> dict[str, str]:
    return {g["field"]: g["raw"] for g in c["gold_rx" if name == "rx" else "gold_label"]}


BENCH_DIR: Path | None = None


def _ocr(c: dict[str, Any], name: str) -> list[OcrLine]:
    """OCR lines for a benchmark image, recomputed with the current engine and cached next to the image."""
    from ..perception.grounding import ocr_lines

    cache = BENCH_DIR / "ocr_cache" / f"{c['case_id']}_{name}.json"
    if cache.exists():
        return [OcrLine(**l) for l in json.loads(cache.read_text(encoding="utf-8"))]
    lines = ocr_lines((BENCH_DIR / f"{c['case_id']}_{name}.jpg").read_bytes())
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps([l.__dict__ for l in lines]), encoding="utf-8")
    return lines


def regrounded(c: dict[str, Any], name: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rec = c["run"]["images"][name]
    lines = _ocr(c, name)
    image = (BENCH_DIR / f"{c['case_id']}_{name}.jpg").read_bytes()
    obs = ground([o for o in rec["extraction"]["observations"]], lines, image)
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


def train_head(rows: list[dict[str, Any]], max_extra_confirm: float = 0.05) -> dict[str, Any]:
    import lightgbm as lgb
    from sklearn.isotonic import IsotonicRegression
    from sklearn.metrics import roc_auc_score

    feats = reliability.FEATURES
    X = lambda rs: np.array([[r["x"][k] for k in feats] for r in rs], dtype=np.float32)
    y = lambda rs: np.array([r["y"] for r in rs])
    tr = [r for r in rows if r["split"] == "train"]
    va = [r for r in rows if r["split"] == "val"]
    te = [r for r in rows if r["split"] == "test"]
    params = dict(objective="binary", learning_rate=0.05, num_leaves=15, min_data_in_leaf=10, feature_fraction=0.8,
                  bagging_fraction=0.8, bagging_freq=1, lambda_l2=1.0, verbose=-1, seed=7)
    booster = lgb.train(params, lgb.Dataset(X(tr), y(tr)), num_boost_round=300)
    iso = IsotonicRegression(out_of_bounds="clip", y_min=0, y_max=1).fit(booster.predict(X(va)), y(va))
    grid = np.linspace(0, 1, 101)
    calib = {"x": grid.tolist(), "y": iso.predict(grid).tolist()}
    meta = {"features": feats, "calibration": calib}

    def cal(rs):
        return np.interp(booster.predict(X(rs)), grid, calib["y"])

    # The head only vetoes readings OCR already corroborated. Threshold on the validation fold: the highest t
    # that sends at most max_extra_confirm of the corroborated high-risk readings to the pharmacist.
    hv = [r for r in va if r["field"] in CORROBORATION_REQUIRED and r["corroboration"] == "corroborated"]
    pv = cal(hv)
    thr = 0.0
    for t in np.linspace(0.999, 0.0, 1000):
        if (pv < t).mean() <= max_extra_confirm:
            thr = float(t)
            break
    meta["threshold"] = thr
    meta["trained_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    meta["max_extra_confirm"] = max_extra_confirm

    report = {"threshold": thr, "n_train": len(tr), "n_val": len(va), "n_test": len(te)}
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
    report["top_features"] = [f for f, _ in sorted(zip(feats, imp), key=lambda t: -t[1])[:8]]
    return {"booster": booster, "meta": meta, "report": report}


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

    trust = [({**o, "requires_confirmation": False, "alternatives": o.get("alternatives", [])}, n)
             for n, (obs, _, _) in obs_by.items() for o in obs if o.get("method") != "ocr-second"]
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
                if y is None:
                    continue
                per[o["field"]][0] += y
                per[o["field"]][1] += 1
            for f in gold:
                if f in SCORED and not any(o["field"] == f for o in c["run"]["images"][name]["extraction"]["observations"]):
                    per[f][1] += 1  # omitted field counts as a miss
    fields = {f: round(a / b, 4) for f, (a, b) in sorted(per.items()) if b}
    return {"field_exact": fields, "readings": total, "fields_not_in_gold": halluc}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bench", default=str(ROOT / "bench_out" / "v1"))
    ap.add_argument("--run", default="local-omni-iq4xs")
    ap.add_argument("--train-head", action="store_true")
    ap.add_argument("--out", default=str(ROOT / "benchmarks" / "results"))
    args = ap.parse_args()
    global BENCH_DIR
    bench = Path(args.bench)
    BENCH_DIR = bench
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    cases = load(bench, args.run)
    print(f"{len(cases)} cases with extractions", Counter(c["split"] for c in cases))

    head_report = None
    if args.train_head:
        rows = dataset(cases, bench)
        print(f"reliability dataset: {len(rows)} readings", Counter(r["split"] for r in rows))
        h = train_head(rows)
        reliability.MODEL_DIR.mkdir(parents=True, exist_ok=True)
        h["booster"].save_model(str(reliability.MODEL_DIR / "head.txt"))
        (reliability.MODEL_DIR / "head.json").write_text(json.dumps(h["meta"], indent=1), encoding="utf-8")
        reliability.load_head.cache_clear()
        head_report = h["report"]
        (out / "reliability_head.json").write_text(json.dumps(head_report, indent=1), encoding="utf-8")
        print(json.dumps(head_report, indent=1))

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
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    (out / f"bench_{args.run}.json").write_text(json.dumps(full, indent=1), encoding="utf-8")
    (out / f"cases_{args.run}.json").write_text(json.dumps(results, indent=1), encoding="utf-8")
    write_summary(full, out)
    for v in variants:
        print(v, json.dumps(by_split.get("test", by_split["all"])[v]))


def reader_name(run: str) -> str:
    return "Nemotron 3 Nano Omni" if "omni" in run else "DeepSeek V4.1 Flash + Nemotron 3 Nano"


def names(reader: str) -> dict[str, str]:
    return {"oracle": "Kernel on gold facts", "omni_trust": f"{reader} readings trusted as read",
            "rxlint_strict": "RxLint: reader + OCR corroboration", "rxlint_head": "RxLint: + reliability head",
            "ocr_rules": "OCR + regex + same kernel"}


def write_summary(full: dict[str, Any], out: Path) -> None:
    reader = reader_name(full["run"])
    NAMES = names(reader)
    split = "test" if "test" in full["scores"] else "all"
    s = full["scores"][split]
    cols = ["System", "False-safe", "False-safe after confirmation", "Review recall", "Exact verdict", "Clean PASS", "Asked to confirm", "Exact after confirmation"]
    rows = [{"System": NAMES[v], "False-safe": m["false_safe"], "False-safe after confirmation": m["false_safe_after_confirmation"],
             "Review recall": m["review_recall"], "Exact verdict": m["exact_verdict"], "Clean PASS": m["clean_pass_rate"],
             "Asked to confirm": m["confirmation_requests"], "Exact after confirmation": m["exact_verdict_after_confirmation"]}
            for v, m in s.items()]
    best = s.get("rxlint_head") or s.get("rxlint_strict")
    trust = s["omni_trust"]
    # What separates RxLint from trusting the reader comes first; the false-safe count, which the kernel
    # keeps at zero for both, comes last with the baseline beside it.
    headline = [
        {"label": "ambiguous handwritten entries held for confirmation", "value": best["ambiguous_blocked"],
         "note": f"{trust['ambiguous_blocked']} when readings are trusted as read"},
        {"label": "exact verdict after pharmacist confirmation", "value": f"{best['exact_verdict_after_confirmation'] * 100:.1f}%",
         "note": f"{trust['exact_verdict_after_confirmation'] * 100:.1f}% when readings are trusted as read"},
    ]
    r = full.get("reliability_head")
    if r and f"{split}_head_false_accept" in r:
        headline.append({"label": "wrong high-risk readings past the gate", "value": f"{r[f'{split}_head_false_accept']}/{r[f'{split}_high_risk_readings']}",
                         "note": f"{r[f'{split}_strict_false_accept']} with OCR corroboration alone"})
    headline.append({"label": f"false-safe cases, RxLint ({split} fold)", "value": best["false_safe"],
                     "note": f"error cases returned as PASS; {trust['false_safe']} when readings are trusted as read"})
    tables = [{"title": f"End-to-end verdicts, {split} fold ({s['oracle']['cases']} cases)",
               "note": "unseen handwriting font, perturbations and product" if split == "test" else "", "columns": cols, "rows": rows}]
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
               "description": f"Run {full['run']}: {full['cases']} cases. Perception by {reader}; every verdict by the deterministic kernel."}
    (out / "summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
