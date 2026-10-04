"""Retrieve public medicine photos with Wikimedia's per-file license metadata.

List before selecting: python tools/collect_public_photos.py --category Amoxicillin
Download explicitly selected files: python tools/collect_public_photos.py --file 'Name.jpg'
No patient records or identities are requested. Review pixels and annotate before evaluation.
"""
import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--category", action="append", default=[])
    ap.add_argument("--file", action="append", default=[])
    args = ap.parse_args()
    with httpx.Client(headers={"User-Agent": "RxLintResearch/0.1 (public medicine image evaluation)"}, timeout=45, follow_redirects=True) as client:
        def api(params):
            r = client.get("https://commons.wikimedia.org/w/api.php", params={"format": "json", **params})
            r.raise_for_status()
            return r.json()
        for category in args.category:
            data = api({"action": "query", "list": "categorymembers", "cmtitle": f"Category:{category}",
                        "cmtype": "file", "cmlimit": 100})
            print(category, [x["title"] for x in data.get("query", {}).get("categorymembers", [])])
        for filename in args.file:
            title = filename if filename.startswith("File:") else f"File:{filename}"
            data = api({"action": "query", "titles": title, "prop": "imageinfo", "iiprop": "url|extmetadata|sha1", "iiurlwidth": 1600})
            info = next(iter(data["query"]["pages"].values())).get("imageinfo", [])
            if not info:
                raise ValueError(f"file not found: {title}")
            info = info[0]
            meta = info["extmetadata"]
            plain = lambda key: re.sub("<[^>]+>", "", meta.get(key, {}).get("value", "")).strip()
            license_name, license_url = plain("LicenseShortName"), plain("LicenseUrl")
            if not (license_name.startswith(("CC BY", "CC0")) or license_name in ("Public domain", "PD")):
                raise ValueError(f"review license manually before downloading: {title}: {license_name}")
            url = info.get("thumburl") or info["url"]
            image = client.get(url)
            image.raise_for_status()
            cid = "commons_" + hashlib.sha256(title.encode()).hexdigest()[:10]
            dest = ROOT / "benchmarks" / "real_world" / cid
            dest.mkdir(parents=True, exist_ok=True)
            (dest / "label.jpg").write_bytes(image.content)
            provenance = {"case_id": cid, "source_type": "real_medicine_photograph", "evaluation_scope": "perception_only",
                "file_title": title, "source_url": info["descriptionurl"], "download_url": url,
                "original_url": info["url"], "author": plain("Artist"), "license": license_name,
                "license_url": license_url, "attribution": plain("Attribution"),
                "sha256": hashlib.sha256(image.content).hexdigest(), "retrieved_at": datetime.now(timezone.utc).isoformat(),
                "annotation_status": "pending_manual_review", "notes": "1600px source thumbnail; no synthetic transformations"}
            (dest / "provenance.json").write_text(json.dumps(provenance, indent=2, ensure_ascii=False), encoding="utf8")
            print(cid, title, license_name, flush=True)


if __name__ == "__main__": main()
