"""Snapshot the source text every rule quotes, so quotes are verifiable offline.

Usage:
    python tools/build_sources.py --aware path/to/aware_book_2022.pdf --labels path/to/labels_dir

Writes rulepacks/pediatric-oral-antibiotics/sources/who-aware-2022-pages.json with the text of each
cited PDF page, and sources/fda-labels.json with the cited sections of each openFDA label.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import yaml

PACK = Path(__file__).resolve().parents[1] / "rulepacks" / "pediatric-oral-antibiotics"

LABEL_FILES = {
    "FDA-LABEL-AMOXICILLIN": "AMOXICILLIN.json",
    "FDA-LABEL-AMOXICILLIN-CLAVULANATE": "AMOXICILLIN_AND_CLAVULANATE_POTASSIUM.json",
    "FDA-LABEL-CEPHALEXIN": "CEPHALEXIN.json",
    "FDA-LABEL-AZITHROMYCIN": "AZITHROMYCIN.json",
    "FDA-LABEL-CLARITHROMYCIN": "CLARITHROMYCIN.json",
    "FDA-LABEL-PENICILLIN-V": "PENICILLIN_V_POTASSIUM.json",
    "FDA-LABEL-SMX-TMP": "SULFAMETHOXAZOLE_AND_TRIMETHOPRIM.json",
}
LABEL_SECTIONS = ["contraindications", "drug_interactions", "warnings_and_cautions", "warnings"]


def cited_pages() -> set[int]:
    pages: set[int] = set()
    for rule in iter_rules():
        for src in [rule.get("source", {})] + rule.get("related_sources", []):
            loc = src.get("locator")
            if isinstance(loc, dict) and "pdf_page" in loc:
                pages.add(int(loc["pdf_page"]))
    return pages


def iter_rules():
    pack = yaml.safe_load((PACK / "pack.yaml").read_text(encoding="utf-8"))
    for rel in pack["rule_files"]:
        data = yaml.safe_load((PACK / rel).read_text(encoding="utf-8"))
        yield from (data["rules"] if isinstance(data, dict) else data)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--aware", required=True)
    ap.add_argument("--labels", required=True)
    args = ap.parse_args()

    import fitz  # PyMuPDF

    pdf = Path(args.aware)
    doc = fitz.open(pdf)
    pages = sorted(cited_pages() | {335})
    out = {
        "source": "WHO-AWARE-2022",
        "sha256": hashlib.sha256(pdf.read_bytes()).hexdigest(),
        "license": "CC BY-NC-SA 3.0 IGO. (c) World Health Organization 2022. Excerpts reproduced for verification.",
        "pages": {str(p): doc[p - 1].get_text() for p in pages},
    }
    (PACK / "sources").mkdir(exist_ok=True)
    (PACK / "sources" / "who-aware-2022-pages.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")

    labels = {}
    for ref, fname in LABEL_FILES.items():
        raw = json.loads((Path(args.labels) / fname).read_text(encoding="utf-8"))["results"][0]
        labels[ref] = {
            "set_id": raw.get("set_id"),
            "version": raw.get("version"),
            "effective_time": raw.get("effective_time"),
            "sections": {k: " ".join(raw[k]) for k in LABEL_SECTIONS if k in raw},
        }
    (PACK / "sources" / "fda-labels.json").write_text(json.dumps(labels, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"wrote {len(pages)} WHO pages and {len(labels)} labels")


if __name__ == "__main__":
    main()
