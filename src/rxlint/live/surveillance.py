"""Plane B: live regulator surveillance for the identified product.

Deterministic code builds the queries from canonical product fields, Tavily searches only the
allowlisted regulator domains for the dispensing country, every URL is re-checked against the
allowlist, a shortlist is extracted, and a deterministic matcher decides applicability:

* ``lot_recall``        the notice names this product and this lot
* ``product_recall``    the notice names this product and lists no lot codes
* ``other_lot``         the notice names this product but lists other lots only (negative control)
* ``safety_communication`` a safety notice about the ingredient
* ``supply_notice``     a shortage or availability notice about the product
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
    s = "".join(ch for ch in s if not unicodedata.combining(ch)).replace("’", "'").replace("ʼ", "'")
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
    others = {c: [a for a in n.ingredients[c]["aliases"] if len(a) > 3] for c in n.ingredients if c not in comps}
    return {"components": comps, "aliases": aliases, "display": display, "ingredient": n.ingredients[comps[0]]["display"],
            "other_ingredients": others}


def lot_pattern(lot: str) -> re.Pattern[str]:
    core = re.sub(r"^(lot|batch)\s*", "", lot, flags=re.I)
    return re.compile(r"(?<![A-Za-z0-9])" + re.escape(core) + r"(?![A-Za-z0-9])", re.I)


# A lot code is an upper-case token containing a digit: "lots concernés" or "two lots distributed" must
# not read as lot codes, or a recall of this product would be filed as a recall of other lots only.
_LOT_CODE = r"(?=[A-Z\-]*\d)[A-Z0-9][A-Z0-9\-]{3,}(?![A-Za-z0-9])"
LOT_LIST = re.compile(
    r"(?i:\b(?:lots?\s*(?:#|no\.?|numbers?|n°)?|batch(?:es)?|numéros?\s+de\s+lots?))\s*[#:]?\s*"
    rf"({_LOT_CODE}(?:\s*(?:,|;|/|&|\band\b|\bet\b)\s*{_LOT_CODE})*)")
_YEAR = re.compile(r"(?:19|20)\d\d")


def listed_lot_codes(text: str) -> list[str]:
    codes = {c for m in LOT_LIST.finditer(text) for c in re.findall(_LOT_CODE, m.group(1))}
    return sorted(c for c in codes if not _YEAR.fullmatch(c))


# Markdown links are navigation and related-news lists: a recall linked from a product page is a notice
# about the linked page, not about the page that links to it.
_MD_LINK = re.compile(r"!?\[([^\]]*)\]\([^)]*\)")


def strip_links(text: str) -> str:
    return _MD_LINK.sub(" ", text or "")


def _near(t: str, words: list[str], positions: list[int], window: int = 400, within: int | None = None) -> bool:
    """True when one of ``words`` occurs within ``window`` characters of one of ``positions`` (and, with
    ``within``, in the first ``within`` characters of ``t``)."""
    for w in words:
        for m in re.finditer(re.escape(_fold(w)), t):
            if within is not None and m.start() > within:
                break
            if any(abs(m.start() - p) <= window for p in positions):
                return True
    return False


# A notice announces itself in its title and opening paragraphs. Deep inside a long document (a product
# register, a meeting report, the Orange Book), "withdrawn" near an ingredient name is not a notice about
# this product, unless it sits next to this product's lot.
LEAD_CHARS = 2500


def match_notice(text: str, title: str, terms: dict[str, Any], lot: str | None, lang: str) -> dict[str, Any]:
    """Deterministic applicability of one regulator page to this product and lot."""
    text = strip_links(text)
    t = _fold(title + "\n" + text)
    comp_hits = {c: any(_fold(a) in t for a in al) for c, al in terms["aliases"].items()}
    product_named = all(comp_hits.values())
    # A combination product must not match a single-ingredient notice and vice versa: a title that names
    # this product together with another active ingredient is a notice about a different product.
    title_f = _fold(title)
    extra = [c for c, al in terms.get("other_ingredients", {}).items() if any(_fold(a) in title_f for a in al)]
    if product_named and extra and all(any(_fold(a) in title_f for a in al) for al in terms["aliases"].values()):
        product_named = False
    words = policies()["recall_words"]["en"] + policies()["recall_words"].get(lang, [])
    safety = policies()["safety_words"]["en"] + policies()["safety_words"].get(lang, [])
    supply = policies()["supply_words"]["en"] + policies()["supply_words"].get(lang, [])
    # The recall or safety wording must sit close to the product name, in the notice's title or opening:
    # a long report that mentions the ingredient on one page and a withdrawal on another is not a notice
    # about this product.
    alias_at = [m.start() for al in terms["aliases"].values() for a in al for m in re.finditer(re.escape(_fold(a)), t)]
    lot_at = [m.start() for m in lot_pattern(lot).finditer(t)] if lot else []
    is_recall = _near(t, words, alias_at, within=LEAD_CHARS) or _near(t, words, lot_at)
    is_safety = _near(t, safety, alias_at, within=LEAD_CHARS)
    lead = t[:1200]  # search titles are truncated, so the opening of the page counts as its title
    is_supply = any(_fold(w) in lead for w in supply)
    lot_hit = bool(lot and lot_pattern(lot).search(title + " " + text))
    listed_lots = listed_lot_codes(title + " " + text)
    matched = [f"ingredient:{c}" for c, ok in comp_hits.items() if ok] + [f"other_product:{c}" for c in extra]
    if lot_hit:
        matched.append("lot")
    if not product_named:
        mtype = "not_applicable"
    elif is_recall and lot_hit:
        mtype = "lot_recall"
    elif (is_recall or is_safety) and listed_lots:
        # A notice that lists lot codes acts on those lots only; this lot is not among them.
        mtype = "other_lot"
    elif is_supply:
        # A shortage or supply notice is published in the regulator's safety section but says nothing
        # about the quality of the bottle in hand.
        mtype = "supply_notice"
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
        # The lot query quotes the lot code and asks Tavily for an exact match, so only pages that print
        # this lot come back; the product and safety queries cast the wider net.
        queries: list[tuple[str, bool]] = []
        if lot_core:
            queries.append((tpl["recall_lot"].format(product=terms["display"], lot=lot_core), True))
        queries.append((tpl["recall"].format(product=terms["display"]), False))
        if auth["authority"] != "WHO":
            queries.append((tpl["safety"].format(ingredient=terms["ingredient"]), False))
        for q, exact in queries:
            if auth.get("query_prefix"):
                q = f"{auth['query_prefix']} {q}"
            try:
                data = tavily.search(q, include_domains=auth["domains"], max_results=5, exact_match=exact)
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
                                                      "authority": auth["authority"], "lang": lang, "queries": [], "exact_lot": False})
                c["queries"].append(q)
                c["exact_lot"] = c["exact_lot"] or exact
            searches.append({"source": f"Tavily search ({auth['authority']})", "query": q, "domains": auth["domains"],
                             "exact_match": exact, "ok": True, "results": kept, "rejected_off_allowlist": rejected})

    # 3. Shortlist deterministically and extract the full pages. A page returned by the exact lot query
    # prints the lot somewhere, even when the search snippet does not show it.
    def pre_score(c: dict[str, Any]) -> float:
        terms = product_terms(n, product, c["lang"])
        m = match_notice(c["content"], c["title"], terms, lot_core, c["lang"])
        return ((3 if "lot" in m["matched_fields"] or c["exact_lot"] else 0) + (2 if m["match_type"] != "not_applicable" else 0)
                + float(c["score"] or 0))

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
        published = iso_date(c.get("published_date")) or iso_date(_first_date(text, c["lang"]), c["lang"])
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
FR_MONTHS = {m: i for i, m in enumerate(["janvier", "fevrier", "mars", "avril", "mai", "juin", "juillet", "aout", "septembre",
                                           "octobre", "novembre", "decembre"], 1)}


def iso_date(s: str | None, lang: str = "en") -> str | None:
    """'March 13, 2026', '13 March 2026', '2026-03-13', an RFC 1123 date, '18 janvier 2019' or, on a French
    page, '18/01/2019' -> ISO date. A numeric day/month date is read only where the page's language fixes
    the order."""
    if not s:
        return None
    t = _fold(s.strip())
    m = re.search(r"((?:19|20)\d\d)-(\d\d)-(\d\d)", t)
    if m:
        return m.group(0)
    if lang == "fr":
        m = re.search(r"\b(\d{1,2})[/.](\d{1,2})[/.]((?:19|20)\d\d)\b", t)
        if m and 1 <= int(m.group(2)) <= 12:
            return f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"
        m = re.search(r"\b(\d{1,2})(?:er)?\s+([a-z]+)\s+((?:19|20)\d\d)", t)
        if m and m.group(2) in FR_MONTHS:
            return f"{m.group(3)}-{FR_MONTHS[m.group(2)]:02d}-{int(m.group(1)):02d}"
    m = re.search(r"(\d{1,2})\s+([a-z]+)\s+((?:19|20)\d\d)", t) or re.search(r"([a-z]+)\s+(\d{1,2}),?\s+((?:19|20)\d\d)", t)
    if m:
        a, b, y = m.groups()
        day, mon = (a, b) if a.isdigit() else (b, a)
        k = mon[:3]
        num = next((v for name, v in MONTHS.items() if name.startswith(k)), None)
        if num:
            return f"{y}-{num:02d}-{int(day):02d}"
    return None


_EN_DATE = (r"(?:19|20)\d\d-\d\d-\d\d|\d{1,2} (?:January|February|March|April|May|June|July|August|September|October|November|December) "
            r"(?:19|20)\d\d|(?:January|February|March|April|May|June|July|August|September|October|November|December) \d{1,2}, (?:19|20)\d\d")


def _first_date(text: str, lang: str = "en") -> str | None:
    text = text or ""
    if lang == "fr":
        # ANSM pages print "Publié le 18/01/2019 - mis à jour le ..."; the publication date wins over
        # later dates such as the update or the print date.
        m = re.search(r"publi[ée]e?\s+le\s+(\d{1,2}[/.]\d{1,2}[/.](?:19|20)\d\d|\d{1,2}(?:er)?\s+\w+\s+(?:19|20)\d\d)", text, re.I)
        if m:
            return m.group(1)
        m = re.search(r"\b(\d{1,2}[/.]\d{1,2}[/.](?:19|20)\d\d)\b", text)
        if m:
            return m.group(1)
    m = re.search(rf"\b({_EN_DATE})\b", text)
    return m.group(1) if m else None
