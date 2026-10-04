"""External photo evaluation; never fabricates prescription/patient data or clinical verdicts."""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from ..config import load_env
from ..core import Normalizer, load_pack
from ..core import EvidenceKind, Observation, SnapshotBuilder
from ..core.snapshot import FIELD_MAP
from ..core.units import parse_strength
from ..models.client import ModelClient
from ..perception import grounding, reliability, refine
from ..perception.transcribe import extract_two_stage
from ..pipeline import _obs_from_extraction


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", default="benchmarks/real_world")
    ap.add_argument("--out", default="benchmarks/results/real_world")
    ap.add_argument("--run", default="review-v2")
    ap.add_argument("--model-dir", help="evaluate a staged reliability head")
    ap.add_argument("--mode", choices=["auto", "record", "replay"], default="auto")
    args = ap.parse_args()
    load_env()
    if args.model_dir:
        reliability.MODEL_DIR = Path(args.model_dir)
        reliability.load_head.cache_clear()
    dataset, out = Path(args.dataset), Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    client = ModelClient(mode=args.mode, cassette=out / f"{args.run}.cassette.jsonl")
    pack = load_pack(); n = Normalizer(pack)
    counts = defaultdict(lambda: {"exact": 0, "total": 0, "autonomous": 0, "wrong_autonomous": 0})
    records = []; errors = []
    strength_strata = defaultdict(lambda: {"exact": 0, "total": 0})
    for p in sorted(dataset.glob("*/ground_truth.json")):
        gt = json.loads(p.read_text(encoding="utf8"))
        provenance = json.loads((p.parent/"provenance.json").read_text(encoding="utf8"))
        image = (p.parent/"label.jpg").read_bytes()
        if hashlib.sha256(image).hexdigest() != provenance["sha256"]:
            raise ValueError(f"source image hash mismatch: {p.parent.name}")
        ex = extract_two_stage(client, image, "medicine", p.parent.name)
        if ex.error:
            errors.append({"case_id": gt["case_id"], "error": ex.error})
        obs = [] if ex.error else _obs_from_extraction(ex, grounding.ocr_lines(image), image, pack, client)
        builder = SnapshotBuilder(n, gt["case_id"])
        for o in obs:
            builder.add(Observation(field=o["field"], raw=o["text"], kind=EvidenceKind.VISUAL_OBSERVATION,
                legible=o.get("legible", True), alternatives=o.get("alternatives", []),
                requires_confirmation=o.get("requires_confirmation", False), confidence=o.get("confidence")))
        snapshot = builder.build()
        fields = []
        for g in gt["gold_label"]:
            field = g["field"]
            expected = reliability.canonical(field, g["raw"], n)
            if expected is None:
                raise ValueError(f"gold cannot be parsed: {p}: {g}")
            predictions = [o for o in obs if o["field"] == field and "second reader" not in o.get("method", "")]
            values = {reliability.canonical(field, o["text"], n) for o in predictions}
            exact = values == {expected}
            # Field acceptance uses the same reconciliation and parsing as the production kernel.
            fact = snapshot.fact(FIELD_MAP[field])
            accepted = fact.status == "present"
            accepted_exact = accepted and all(reliability.canonical(field, o["text"], n) == expected
                for o in obs if o["field"] == field and reliability.canonical(field, o["text"], n) is not None)
            c = counts[field]; c["total"] += 1; c["exact"] += int(exact)
            if field == "dispensed.strength":
                group = "liquid_concentration" if parse_strength(g["raw"]).per_ml is not None else "solid_strength"
                strength_strata[group]["total"] += 1
                strength_strata[group]["exact"] += int(exact)
            c["autonomous"] += int(accepted); c["wrong_autonomous"] += int(accepted and not accepted_exact)
            fields.append({"field": field, "exact": exact, "autonomous": accepted,
                           "accepted_exact": accepted_exact, "expected": g["raw"], "readings": [o["text"] for o in predictions]})
        absent = gt.get("absent_fields", [])
        invented = [o for o in obs if o["field"] in absent]
        records.append({"case_id": gt["case_id"], "source": provenance, "fields": fields,
            "invented_absent_fields": invented, "observations": obs, "extraction": ex.model_dump()})
        print(gt["case_id"], f"{sum(x['exact'] for x in fields)}/{len(fields)} fields exact", flush=True)
    report = {"evaluation_scope": "external_real_photograph_perception_only", "run": args.run,
        "images": len(records), "expected_images": len(list(dataset.glob('*/ground_truth.json'))),
        "label_images": sum(bool(r["fields"]) for r in records), "negative_controls": sum(not r["fields"] for r in records),
        "failed_images": len(errors), "ocr_fingerprint": grounding.fingerprint(),
        "field_results": {f: {**c, "exact_rate": c["exact"]/c["total"]} for f,c in counts.items()},
        "strength_by_printed_form": dict(strength_strata),
        "product_audit_version": refine.PRODUCT_AUDIT_VERSION,
        "reliability_head_sha256": hashlib.sha256((reliability.MODEL_DIR/"head.txt").read_bytes()).hexdigest(),
        "absent_field_hallucinations": sum(len(r["invented_absent_fields"]) for r in records),
        "errors": errors, "generated_at": datetime.now(timezone.utc).isoformat(),
        "limitations": ["Convenience sample of public medicine photographs; no paired prescriptions or patient facts",
            "Single visual annotator; no pharmacist adjudication", "Includes tablets and non-English packaging",
            "Multiple images by the same photographers; not statistically independent", "No clinical safety/verdict claims"]}
    (out/f"{args.run}.json").write_text(json.dumps(report,indent=2),encoding="utf8")
    (out/f"{args.run}_cases.json").write_text(json.dumps(records,indent=2,ensure_ascii=False),encoding="utf8")
    print(json.dumps(report,indent=2))


if __name__ == "__main__": main()
