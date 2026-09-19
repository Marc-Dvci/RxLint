"""Run every demo case through the full pipeline and print verdict against expectation.

With RXLINT_MODEL_MODE=record the model responses are stored in fixtures/model_cassette.jsonl,
which the hosted demo replays when no model endpoint is reachable.
"""
import os
import sys
from pathlib import Path

from rxlint import demo
from rxlint.config import load_env

load_env()
from rxlint.core import load_pack
from rxlint.models.client import ModelClient
from rxlint.pipeline import Asset, CaseInput, run_case

pack = load_pack()
ids = sys.argv[1:] or [c.id for c in demo.CASES]
ok = 0
for cid in ids:
    c = demo.BY_ID[cid]
    paths = {slot: demo.photo(cid, slot) for slot in ("rx", "label")}
    blobs = {slot: p.read_bytes() for slot, p in paths.items()}
    assets = [Asset.from_bytes("rx", "prescription", blobs["rx"], demo.mime(paths["rx"])),
              Asset.from_bytes("label", "medicine", blobs["label"], demo.mime(paths["label"]))]
    client = ModelClient(mode=os.environ.get("RXLINT_MODEL_MODE", "record"))
    r = run_case(CaseInput(case_id=cid, assets=assets, patient=c.patient, country=c.country, dispense_date=c.dispense_date),
                 blobs, client, pack, use_ultra=os.environ.get("RXLINT_DEMO_ULTRA", "0") == "1")
    v = r.verification
    ok += v["state"] == c.expect
    print(f"{cid}: expect {c.expect:13} got {v['state']:13} {'OK' if v['state'] == c.expect else 'MISMATCH'}  flagged={r.untrusted_text_flagged}")
    for f in v["findings"]:
        if f["status"] in ("fail", "cannot_evaluate", "out_of_scope"):
            print(f"      {f['rule_id']:20} {f['message'][:110]}")
print(f"{ok}/{len(ids)} demo cases match their expected verdict")
