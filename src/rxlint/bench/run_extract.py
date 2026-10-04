"""Run perception (Nano Omni + OCR grounding) over a rendered RxLintBench set.

Resumable: one JSON file per case under ``<bench>/extractions/<run>/``. Model responses are also
recorded to a cassette so the run can be replayed without the model.

    python -m rxlint.bench.run_extract --bench bench_out/v1 --run local-omni-iq4xs --workers 2
"""

from __future__ import annotations

import argparse
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from ..models.client import ModelClient
from ..config import load_env
from ..perception.extraction import extract_image
from ..perception.transcribe import extract_two_stage
from ..perception.grounding import ground, ocr_lines
from ..perception import grounding, refine


def process(case: dict, bench: Path, out: Path, client: ModelClient, reader=extract_image) -> str:
    dest = out / f"{case['case_id']}.json"
    if dest.exists():
        return "skip"
    rec: dict = {"case_id": case["case_id"], "images": {}}
    for name, kind in (("rx", "prescription"), ("label", "medicine")):
        data = (bench / f"{case['case_id']}_{name}.jpg").read_bytes()
        t = time.perf_counter()
        ex = reader(client, data, kind, f"{case['case_id']}_{name}", mime="image/jpeg")
        if ex.error:
            raise RuntimeError(f"{name} extraction failed: {ex.error}")
        lat = int((time.perf_counter() - t) * 1000)
        lines = ocr_lines(data)
        obs = ground(refine.recover([o.model_dump() for o in ex.observations], lines, kind), lines, data)
        obs = refine.validate_products(refine.validate(refine.resolve(obs, data, client)), ex.transcript, kind)
        rec["images"][name] = {
            "extraction": ex.model_dump(), "grounded": obs, "latency_ms": lat,
            "ocr": [{"text": l.text, "bbox": l.bbox, "score": l.score} for l in lines],
            "ocr_fingerprint": grounding.fingerprint(), "refinement_version": refine.VERSION,
        }
    dest.write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")
    return "ok"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bench", required=True)
    ap.add_argument("--run", required=True)
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--split", default=None)
    ap.add_argument("--reader", choices=["omni", "two_stage"], default="omni")
    # auto replays what the cassette already holds (for example the transcripts of a run that shared the
    # vision model) and calls the model for the rest.
    ap.add_argument("--mode", choices=["record", "auto", "replay"], default="record")
    args = ap.parse_args()
    load_env()
    reader = extract_image if args.reader == "omni" else extract_two_stage
    bench = Path(args.bench)
    out = bench / "extractions" / args.run
    out.mkdir(parents=True, exist_ok=True)
    client = ModelClient(mode=args.mode, cassette=bench / "extractions" / f"{args.run}.cassette.jsonl")
    cases = [json.loads(l) for l in (bench / "cases.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    if args.split:
        cases = [c for c in cases if c["split"] == args.split]
    t0 = time.time()
    done = 0
    errors = 0
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futs = {pool.submit(process, c, bench, out, client, reader): c["case_id"] for c in cases}
        for f in as_completed(futs):
            try:
                status = f.result()
            except Exception as exc:  # keep going; the case is retried on the next run
                status = f"error {type(exc).__name__}: {exc}"
                errors += 1
            done += 1
            print(f"[{done}/{len(cases)}] {futs[f]} {status} {time.time() - t0:.0f}s", flush=True)
    if errors:
        raise SystemExit(f"{errors} cases failed; resume the same run before reporting results")


if __name__ == "__main__":
    main()
