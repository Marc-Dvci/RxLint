"""Plane B: live regulator surveillance for the identified product.

Deterministic code builds the queries from canonical product fields, Tavily searches only the
allowlisted regulator domains for the dispensing country, every URL is re-checked against the
allowlist, a shortlist is extracted, and a deterministic matcher decides applicability:

* ``lot_recall``        the notice names this product and this lot
* ``product_recall``    the notice names this product and lists no lot codes
* ``other_lot``         the notice names this product but lists other lots only (negative control)
* ``safety_communication`` a safety notice about the ingredient
* ``not_applicable``    the notice does not name this product

Only ``lot_recall``, ``product_recall`` and ``safety_communication`` produce LIVE_REVIEW. The live
state never changes the deterministic verdict. An empty result means no alert was retrieved from
the configured sources during this check; it is never presented as proof that none exists.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml

from ..core.normalize import Normalizer
from ..core.rulepack import RulePack
from . import openfda
from .tavily import TavilyClient, TavilyUnavailable

POLICY_PATH = Path(__file__).with_name("policies.yaml")


@lru_cache(maxsize=1)
def policies() -> dict[str, Any]:
    return yaml.safe_load(POLICY_PATH.read_text(encoding="utf-8"))


def _fold(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", s.lower())


def allowed(url: str, domains: list[str]) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return any(host == d or host.endswith("." + d) for d in domains)


def product_terms(n: Normalizer, product: str, lang: str) -> dict[str, Any]:
    comps = n.components(product)
    aliases = {c: [a for a in n.ingredients[c]["aliases"] if len(a) > 3] for c in comps}
    display = n.display(product)
    if lang == "fr":
        fr = {"amoxicillin": "amoxicilline", "clavulanic_acid": "acide clavulanique", "cefalexin": "céfalexine",
              "azithromycin": "azithromycine", "clarithromycin": "clarithromycine", "sulfamethoxazole": "sulfaméthoxazole",
              "trimethoprim": "triméthoprime", "phenoxymethylpenicillin": "phénoxyméthylpénicilline"}
        display = " ".join(fr.get(c, c) for c in comps)
    else:
        display = " and ".join(n.ingredients[c]["display"].lower() for c in comps)
    return {"components": comps, "aliases": aliases, "display": display, "ingredient": n.ingredients[comps[0]]["display"]}


def lot_pattern(lot: str) -> re.Pattern[str]:
    core = re.sub(r"^(lot|batch)\s*", "", lot, flags=re.I)
    return re.compile(r"(?<![A-Za-z0-9])" + re.escape(core) + r"(?![A-Za-z0-9])", re.I)


LOT_LIST = re.compile(r"\b(?:lot|lots|batch|lot #|lot no\.?|lot number|numéro de lot|lots?\s*n°)\s*[#:]?\s*([A-Z0-9][A-Z0-9\-]{3,})", re.I)


def match_notice(text: str, title: str, terms: dict[str, Any], lot: str | None, lang: str) -> dict[str, Any]:
    """Deterministic applicability of one regulator page to this product and lot."""
    t = _fold(title + "\n" + text)
    comp_hits = {c: any(_fold(a) in t for a in al) for c, al in terms["aliases"].items()}
    product_named = all(comp_hits.values())
    # A combination product must not match a single-ingredient notice and vice versa.
    words = policies()["recall_words"]["en"] + policies()["recall_words"].get(lang, [])
    safety = policies()["safety_words"]["en"] + policies()["safety_words"].get(lang, [])
    is_recall = any(_fold(w) in t for w in words)
    is_safety = any(_fold(w) in t for w in safety)
    lot_hit = bool(lot and lot_pattern(lot).search(title + " " + text))
    listed_lots = sorted({m.group(1).upper() for m in LOT_LIST.finditer(title + " " + text)})
    matched = [f"ingredient:{c}" for c, ok in comp_hits.items() if ok]
    if lot_hit:
        matched.append("lot")
    if not product_named:
        mtype = "not_applicable"
    elif is_recall and lot_hit:
        mtype = "lot_recall"
    elif is_recall and listed_lots:
        mtype = "other_lot"
    elif is_recall:
        mtype = "product_recall"
    elif is_safety:
        mtype = "safety_communication"
    else:
        mtype = "not_applicable"
    snippet = None
    anchor = lot_pattern(lot).search(text) if lot_hit and lot else None
    if anchor:
        snippet = text[max(0, anchor.start() - 220): anchor.end() + 220]
    elif product_named:
        first = min((t.find(_fold(a)) for al in terms["aliases"].values() for a in al if _fold(a) in t), default=0)
        snippet = (title + "\n" + text)[max(0, first - 120): first + 320]
    return {"match_type": mtype, "matched_fields": matched, "listed_lots": listed_lots[:20],
            "is_recall": is_recall, "is_safety": is_safety, "snippet": (snippet or "").strip()[:600]}


APPLICABLE = {"lot_recall", "product_recall", "safety_communication"}


def live_check(pack: RulePack, product: str | None, lot: str | None, country: str | None, manufacturer: str | None = None,
               tavily: TavilyClient | None = None, as_of: str | None = None, use_openfda: bool = True) -> dict[str, Any]:
    tavily = tavily or TavilyClient()
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    base = {"retrieved_at": now, "as_of": as_of, "query_policy": policies()["version"], "country": country,
            "target": {"product": product, "lot": lot, "manufacturer": manufacturer}, "clinical_rule_changed": False}
    if not product:
        return {**base, "status": "LIVE_NOT_CONFIGURED", "reason": "product not identified", "notices": [], "searches": []}
    cfg = policies()["countries"].get((country or "").upper())
    if cfg is None:
        return {**base, "status": "LIVE_NOT_CONFIGURED",
                "reason": f"no reviewed regulator-source policy for country {country!r}", "notices": [], "searches": []}
    n = Normalizer(pack)
    authorities = cfg["authorities"] + policies()["international"]
    searches: list[dict[str, Any]] = []
    candidates: dict[str, dict[str, Any]] = {}
    errors: list[str] = []
    lot_core = re.sub(r"^(lot|batch)\s*", "", lot or "", flags=re.I) or None

    # 1. Structured regulator feed (openFDA enforcement) for the US.
    notices: list[dict[str, Any]] = []
    if use_openfda and "openfda_enforcement" in cfg.get("structured_feeds", []):
        try:
            for rec in openfda.enforcement(n, product, lot_core, as_of=as_of):
                notices.append(rec)
            searches.append({"source": "openFDA enforcement", "ok": True, "results": len(notices)})
        except openfda.FeedUnavailable as exc:
            errors.append(f"openFDA: {exc}")
            searches.append({"source": "openFDA enforcement", "ok": False, "error": str(exc)})

    # 2. Tavily search over allowlisted regulator domains.
    if not tavily.configured:
        errors.append("TAVILY_API_KEY is not configured")
        searches.append({"source": "Tavily search", "ok": False, "error": "TAVILY_API_KEY is not configured"})
    for auth in authorities if tavily.configured else []:
        lang = auth.get("lang", "en")
        terms = product_terms(n, product, lang)
        tpl = policies()["templates"][lang]
        queries = []
        if lot_core:
            queries.append(tpl["recall_lot"].format(product=terms["display"], lot=lot_core))
        queries.append(tpl["recall"].format(product=terms["display"]))
        if auth["authority"] != "WHO":
            queries.append(tpl["safety"].format(ingredient=terms["ingredient"]))
        for q in queries:
            if auth.get("query_prefix"):
                q = f"{auth['query_prefix']} {q}"
            try:
                data = tavily.search(q, include_domains=auth["domains"], max_results=5)
            except TavilyUnavailable as exc:
                errors.append(str(exc))
                searches.append({"source": f"Tavily search ({auth['authority']})", "query": q, "ok": False, "error": str(exc)})
                continue
            kept, rejected = 0, 0
            for r in data.get("results", []):
                if not allowed(r.get("url", ""), auth["domains"]):
                    rejected += 1
                    continue
                kept += 1
                c = candidates.setdefault(r["url"], {"url": r["url"], "title": r.get("title", ""), "content": r.get("content", ""),
                                                      "score": r.get("score", 0), "published_date": r.get("published_date"),
                                                      "authority": auth["authority"], "lang": lang, "queries": []})
                c["queries"].append(q)
            searches.append({"source": f"Tavily search ({auth['authority']})", "query": q, "domains": auth["domains"],
                             "ok": True, "results": kept, "rejected_off_allowlist": rejected})

    # 3. Shortlist deterministically and extract the full pages.
    def pre_score(c: dict[str, Any]) -> float:
        terms = product_terms(n, product, c["lang"])
        m = match_notice(c["content"], c["title"], terms, lot_core, c["lang"])
        return (3 if "lot" in m["matched_fields"] else 0) + (2 if m["match_type"] != "not_applicable" else 0) + float(c["score"] or 0)

    shortlist = sorted(candidates.values(), key=pre_score, reverse=True)[:4]
    extracted: dict[str, str] = {}
    if shortlist:
        try:
            data = tavily.extract([c["url"] for c in shortlist])
            for r in data.get("results", []):
                if allowed(r.get("url", ""), [d for a in authorities for d in a["domains"]]):
                    extracted[r["url"]] = r.get("raw_content") or ""
            searches.append({"source": "Tavily extract", "ok": True, "results": len(extracted), "urls": [c["url"] for c in shortlist]})
        except TavilyUnavailable as exc:
            errors.append(str(exc))
            searches.append({"source": "Tavily extract", "ok": False, "error": str(exc)})

    for c in shortlist:
        text = extracted.get(c["url"]) or c["content"]
        terms = product_terms(n, product, c["lang"])
        m = match_notice(text, c["title"], terms, lot_core, c["lang"])
        published = iso_date(c.get("published_date")) or iso_date(_first_date(text))
        if as_of and published and published > as_of:
            # A historical check cannot see notices published after its date.
            m = {**m, "match_type": "after_check_date"}
        notices.append({"source": "Tavily", "authority": c["authority"], "url": c["url"], "title": c["title"],
                        "published_at": published or c.get("published_date"), "retrieved_at": now,
                        "extracted": c["url"] in extracted, **m})

    applicable = [x for x in notices if x["match_type"] in APPLICABLE]
    tavily_ok = any(s.get("ok") for s in searches if s["source"].startswith("Tavily search"))
    feed_ok = any(s.get("ok") for s in searches if s["source"] == "openFDA enforcement")
    if applicable:
        status = "LIVE_REVIEW"
    elif not (tavily_ok or feed_ok) or errors and not tavily_ok:
        status = "LIVE_UNAVAILABLE"
    else:
        status = "LIVE_CLEAR"
    return {**base, "status": status, "notices": sorted(notices, key=lambda x: x["match_type"] not in APPLICABLE),
            "applicable": len(applicable), "searches": searches, "errors": errors,
            "tavily_calls": [c.__dict__ for c in tavily.log],
            "statement": ("No applicable alert was retrieved from the configured sources during this check."
                          if status == "LIVE_CLEAR" else None)}


MONTHS = {m: i for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july", "august", "september",
                                        "october", "november", "december"], 1)}


def iso_date(s: str | None) -> str | None:
    """'March 13, 2026', '13 March 2026', '2026-03-13' or an RFC 1123 date -> '2026-03-13'."""
    if not s:
        return None
    t = s.strip()
    m = re.search(r"(20\d\d)-(\d\d)-(\d\d)", t)
    if m:
        return m.group(0)
    m = re.search(r"(\d{1,2})\s+([A-Za-z]+)\s+(20\d\d)", t) or re.search(r"([A-Za-z]+)\s+(\d{1,2}),?\s+(20\d\d)", t)
    if m:
        a, b, y = m.groups()
        day, mon = (a, b) if a.isdigit() else (b, a)
        k = mon.lower()[:3]
        num = next((v for name, v in MONTHS.items() if name.startswith(k)), None)
        if num:
            return f"{y}-{num:02d}-{int(day):02d}"
    return None


def _first_date(text: str) -> str | None:
    m = re.search(r"\b(20\d\d-\d\d-\d\d|\d{1,2} (?:January|February|March|April|May|June|July|August|September|October|November|December) 20\d\d|(?:January|February|March|April|May|June|July|August|September|October|November|December) \d{1,2}, 20\d\d)\b", text or "")
    return m.group(1) if m else None
