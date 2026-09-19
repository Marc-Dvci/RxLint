"""openFDA drug enforcement reports: a structured U.S. recall feed alongside the Tavily web search."""

from __future__ import annotations

import re
from datetime import date
from typing import Any

import httpx

from ..core.normalize import Normalizer

URL = "https://api.fda.gov/drug/enforcement.json"


class FeedUnavailable(RuntimeError):
    pass


def enforcement(n: Normalizer, product: str, lot: str | None, as_of: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
    comps = n.components(product)
    names = {"clavulanic_acid": "clavulanate", "cefalexin": "cephalexin"}
    terms = " AND ".join(f'product_description:"{names.get(c, c.replace("_", " "))}"' for c in comps)
    search = f"({terms}) AND product_description:suspension"
    try:
        r = httpx.get(URL, params={"search": search, "limit": limit, "sort": "report_date:desc"}, timeout=15)
        if r.status_code == 404:
            return []
        r.raise_for_status()
        results = r.json().get("results", [])
    except Exception as exc:
        raise FeedUnavailable(type(exc).__name__) from exc
    out = []
    for rec in results:
        report = rec.get("report_date")
        if as_of and report and report > as_of.replace("-", ""):
            continue  # not yet published at the historical check date
        desc = rec.get("product_description", "")
        code = rec.get("code_info", "")
        # combination vs single-ingredient must agree
        has_all = all(names.get(c, c.replace("_", " ")).split()[0].lower() in desc.lower() for c in comps)
        if not has_all:
            continue
        if len(comps) == 1 and re.search(r"clavulan|trimethoprim", desc, re.I) and product in ("amoxicillin",):
            continue
        lot_hit = bool(lot and re.search(r"(?<![A-Za-z0-9])" + re.escape(lot) + r"(?![A-Za-z0-9])", code, re.I))
        mtype = "lot_recall" if lot_hit else ("other_lot" if re.search(r"\d{4,}", code) else "product_recall")
        out.append({
            "source": "openFDA", "authority": "FDA", "url": f"https://api.fda.gov/drug/enforcement.json?search=recall_number:{rec.get('recall_number')}",
            "title": f"FDA enforcement report {rec.get('recall_number')} ({rec.get('classification')}, {rec.get('status')})",
            "published_at": _iso(report), "match_type": mtype,
            "matched_fields": [f"ingredient:{c}" for c in comps] + (["lot"] if lot_hit else []),
            "listed_lots": re.findall(r"\b([A-Z0-9]{5,})\b", code)[:20], "snippet": f"{desc[:220]} | {code[:200]} | Reason: {rec.get('reason_for_recall', '')[:200]}",
            "recall_number": rec.get("recall_number"), "recalling_firm": rec.get("recalling_firm"),
            "reason": rec.get("reason_for_recall"), "classification": rec.get("classification"),
            "extracted": True, "is_recall": True, "is_safety": False,
        })
    return out


def _iso(d: str | None) -> str | None:
    if not d or len(d) != 8:
        return d
    return date(int(d[:4]), int(d[4:6]), int(d[6:])).isoformat()
