"""Explanations of established findings, for professionals and for caregivers.

Nemotron 3 Ultra writes connective prose around placeholder tokens such as ``{{v1}}``. Each token
carries a complete value with its unit ("52.63 mg/kg/day"), a medicine name, a rule identifier,
or the fixed verdict and action phrases, all rendered from the verified result. Two checks run
before a model text is shown:

1. Integrity: no digit outside a token, only known tokens, the action token exactly once.
2. Audit: Nemotron 3 Nano answers closed questions about the rendered text, generated from the
   findings ("does the text say the dose is too low or too high?"). An answer that contradicts
   the verified result, such as "too high" where the kernel found "below", rejects the text.

A rejected text is replaced by the deterministic template in the same language.
"""

from __future__ import annotations

import json
import re
from typing import Any

from ..models.client import ModelClient, ModelUnavailable, parse_json
from . import i18n

TOKEN = re.compile(r"\{\{([a-z0-9_]+)\}\}")
PROMPT_VERSION = "explain-v3"

SYSTEM = """You explain the result of a deterministic medication check. The check is already complete; you cannot change it.
Write in {language}. Use the placeholder tokens given (for example {{{{v1}}}}) wherever a value, a medicine name, a rule or the action is needed.
Each token already contains its unit: never add a unit after a token and never move a token to describe a different quantity.
Never write a digit yourself. Never add a clinical recommendation, a new dose, or a fact that is not in the findings.
Say whether a value is above or below a range only as the finding states it.
{audience}
Reply with one JSON object: {{"text": "..."}}."""

AUDIENCE = {
    "professional": "The reader is a pharmacist. Be precise and brief: at most four sentences. Cite the rule tokens given. The action token {{action}} must appear exactly once, as the last sentence.",
    "caregiver": "The reader is a parent or caregiver. Use plain words, at most three short sentences. Do not mention rules. The action token {{action}} must appear exactly once, as the last sentence.",
}

UNIT_WORDS = {
    "mg/day": {"en": "mg/day", "fr": "mg/jour", "ar": "ملغ/يوم", "sw": "mg/siku"},
    "days": {"en": "days", "fr": "jours", "ar": "أيام", "sw": "siku"},
}

def _unit(u: str, lang: str) -> str:
    return i18n.UNITS.get(u, {}).get(lang) or UNIT_WORDS.get(u, {}).get(lang) or u


def _localise_units(s: str, lang: str) -> str:
    for u in ("mg/kg/day", "mg/kg/dose"):
        s = s.replace(u, _unit(u, lang))
    return s


def _claim(f: dict[str, Any]) -> str | None:
    t, st = f["type"], f["status"]
    if st == "cannot_evaluate" or t in ("mandatory_fact", "coverage"):
        return "missing_information"
    if st == "out_of_scope":
        return "out_of_scope"
    if t == "weight_dose":
        return "dose_above_range" if (f.get("facts") or {}).get("direction") == "above" else "dose_below_range"
    return {"concentration_match": "strength_mismatch", "identity_match": "product_mismatch", "form_match": "form_mismatch",
            "max_daily_dose": "above_daily_maximum", "frequency_allowed": "interval_differs", "duration_allowed": "duration_differs",
            "allergy_contraindication": "allergy_conflict", "min_age": "age_contraindication", "expiry": "expiry_problem",
            "quantity": "quantity_insufficient", "interaction": "interaction", "duplicate_ingredient": "duplicate_therapy",
            "duplicate_class": "duplicate_therapy", "indication_option": "other"}.get(t, "other")


def _values(f: dict[str, Any], lang: str) -> dict[str, str]:
    """The values a finding may be explained with, each with its unit attached."""
    x = f.get("facts") or {}
    t = f["type"]
    if t == "concentration_match":
        return {"prescribed_strength": x.get("prescribed_strength"), "dispensed_strength": x.get("dispensed_strength")}
    if t == "identity_match":
        return {"prescribed_medicine": x.get("prescribed"), "dispensed_medicine": x.get("dispensed")}
    if t == "weight_dose":
        return {"child_weight": f"{x.get('weight_kg')} kg", "calculated_dose": f"{x.get('value')} {_unit(x.get('unit', ''), lang)}",
                "guideline_range": _localise_units(str(x.get("range", "")), lang),
                "daily_amount": f"{x.get('mg_per_day')} {_unit('mg/day', lang)}"}
    if t == "max_daily_dose":
        return {"daily_amount": f"{x.get('mg_per_day')} {_unit('mg/day', lang)}", "daily_maximum": f"{x.get('limit_mg')} {_unit('mg/day', lang)}"}
    if t == "duration_allowed":
        return {"prescribed_duration": f"{x.get('days')} {_unit('days', lang)}",
                "guideline_duration": str(x.get("expected", "")).replace("days", _unit("days", lang))}
    if t == "allergy_contraindication":
        return {"reported_allergy": x.get("allergy"), "medicine": x.get("product")}
    if t == "expiry":
        return {"expiry_date": x.get("expiry")}
    if t == "quantity":
        return {"needed_volume": f"{x.get('needed_ml')} mL", "supplied_volume": f"{x.get('supplied_ml')} mL"}
    if t in ("interaction", "duplicate_ingredient", "duplicate_class"):
        return {"current_medicine": x.get("medicine")}
    return {}


def value_table(verification: dict[str, Any], language: str) -> tuple[dict[str, str], list[dict[str, Any]]]:
    """Tokens for the failing findings, the verdict and the action, plus the model-facing finding list."""
    state = verification["state"]
    tokens: dict[str, str] = {"state": i18n.STATE[state][language], "action": i18n.ACTION[state][language]}
    items = []
    n = 0
    for i, f in enumerate(verification["findings"]):
        if f["status"] not in ("fail", "cannot_evaluate", "out_of_scope"):
            continue
        if f["status"] == "fail" and f.get("severity") == "advisory":
            continue
        rule_tok = f"r{i + 1}"
        tokens[rule_tok] = f["rule_id"]
        entry = {"rule": "{{" + rule_tok + "}}", "finding": f["title"], "status": f["status"], "severity": f.get("severity"),
                 "claim": _claim(f), "values": {}}
        if f["status"] == "cannot_evaluate" and f.get("missing"):
            from .clarify import FIELD_WORDS

            entry["blocked_by"] = [FIELD_WORDS.get(m, m.split(".")[-1].replace("_", " ")) for m in f["missing"]]
            entry["reason"] = "could not be read with certainty" if "competing" in f.get("message", "") else "not stated"
        for k, v in _values(f, language).items():
            if v is None or not str(v).strip() or str(v).startswith("None"):
                continue
            n += 1
            tokens[f"v{n}"] = str(v)
            entry["values"][k] = "{{" + f"v{n}" + "}}"
        items.append(entry)
    return tokens, items


def check_integrity(text: str, tokens: dict[str, str], required: list[str]) -> list[str]:
    problems = []
    used = TOKEN.findall(text)
    unknown = [u for u in used if u not in tokens]
    if unknown:
        problems.append(f"unknown tokens {unknown}")
    for r in required:
        if used.count(r) != 1:
            problems.append(f"token {{{{{r}}}}} must appear exactly once")
    stripped = TOKEN.sub("", text)
    if re.search(r"\d", stripped):
        problems.append("free-standing digit outside a token")
    if len(stripped) > 900:
        problems.append("too long")
    if not stripped.strip():
        problems.append("empty")
    return problems


AUDIT_SYSTEM = """You check what a short medical explanation says. Answer each question only from the text, choosing one of the allowed answers.
Answer "not_stated" when the text does not say it. The text may be in any language. Reply with JSON {"answers": {"<question id>": "<answer>"}}."""

# Closed questions per claim: (question, allowed answers, answers that contradict the verified claim)
QUESTIONS = {
    "dose_below_range": ("Does the text say the child's dose is too low (below the range) or too high (above the range)?", ["too_low", "too_high", "not_stated"], {"too_high"}),
    "dose_above_range": ("Does the text say the child's dose is too low (below the range) or too high (above the range)?", ["too_low", "too_high", "not_stated"], {"too_low"}),
    "above_daily_maximum": ("Does the text say the daily amount is above the maximum, or within it?", ["above", "within", "not_stated"], {"within"}),
    "strength_mismatch": ("Does the text say the prescribed and dispensed strengths differ, or that they match?", ["differ", "match", "not_stated"], {"match"}),
    "product_mismatch": ("Does the text say the dispensed medicine is a different medicine from the prescribed one, or the same?", ["different", "same", "not_stated"], {"same"}),
    "duration_differs": ("Does the text say the prescribed duration differs from the guideline, or matches it?", ["differs", "matches", "not_stated"], {"matches"}),
    "allergy_conflict": ("Does the text say the reported allergy conflicts with this medicine, or that there is no conflict?", ["conflict", "no_conflict", "not_stated"], {"no_conflict"}),
    "quantity_insufficient": ("Does the text say the supplied quantity is too small, or enough?", ["too_small", "enough", "not_stated"], {"enough"}),
}
GENERAL = {
    "problem": ("Does the text say there is a problem with this medicine or prescription?", ["yes", "no"]),
    "instruction": ("What does the text tell the reader to do with the medicine?", ["do_not_give_yet", "give_it", "ask_pharmacist", "not_stated"]),
}
EXPECTED = {
    "REVIEW": {"problem": {"yes"}, "instruction": {"do_not_give_yet", "ask_pharmacist"}},
    "CANNOT_VERIFY": {"problem": {"yes", "no"}, "instruction": {"do_not_give_yet", "ask_pharmacist"}},
    "PASS": {"problem": {"no"}, "instruction": {"give_it", "not_stated"}},
    "OUT_OF_SCOPE": {"problem": {"yes", "no"}, "instruction": {"ask_pharmacist", "not_stated"}},
}


def audit(client: ModelClient, text: str, items: list[dict[str, Any]], state: str, audience: str) -> dict[str, Any]:
    """Nemotron answers closed questions about the rendered text; code compares the answers with the result."""
    qs: dict[str, tuple[str, list[str], set[str]]] = {}
    for it in items:
        c = it.get("claim")
        if c in QUESTIONS and c not in qs:
            qs[c] = QUESTIONS[c]
    questions = {k: {"question": q, "allowed": a} for k, (q, a, _) in qs.items()}
    questions.update({k: {"question": q, "allowed": a} for k, (q, a) in GENERAL.items()})
    schema = {"type": "object", "additionalProperties": False, "required": ["answers"],
              "properties": {"answers": {"type": "object", "additionalProperties": False, "required": list(questions),
                                         "properties": {k: {"type": "string", "enum": v["allowed"]} for k, v in questions.items()}}}}
    res = client.chat("structure", [{"role": "system", "content": AUDIT_SYSTEM},
                                    {"role": "user", "content": f"Text:\n{text}\n\nQuestions:\n{json.dumps(questions, ensure_ascii=False, indent=1)}"}],
                      schema=schema, purpose="audit-v2", max_tokens=400)
    answers = parse_json(res.content, res.reasoning).get("answers", {})
    problems = []
    for k, (_, _, bad) in qs.items():
        if answers.get(k) in bad:
            problems.append(f"text contradicts {k} (read as {answers.get(k)})")
    exp = EXPECTED[state]
    if answers.get("problem") not in exp["problem"]:
        problems.append(f"text says problem={answers.get('problem')} for a {state} result")
    if audience == "caregiver" and answers.get("instruction") not in exp["instruction"]:
        problems.append(f"instruction read as {answers.get('instruction')}")
    return {"answers": answers, "problems": problems, "model": res.record.model, "replayed": res.record.replayed}


def render(text: str, tokens: dict[str, str]) -> str:
    return TOKEN.sub(lambda m: tokens[m.group(1)], text)


def deterministic(verification: dict[str, Any], language: str, audience: str) -> str:
    state = verification["state"]
    parts: list[str] = []
    if state == "PASS":
        parts.append(i18n.REASON["_pass"][language])
    elif state == "OUT_OF_SCOPE":
        parts.append(i18n.REASON["_oos"][language])
    else:
        seen = set()
        for f in verification["findings"]:
            if f["status"] == "fail" and f.get("severity") != "advisory" and f["type"] not in seen:
                tpl = i18n.REASON.get(f["type"], i18n.REASON["_default"])[language]
                facts = dict(f.get("facts") or {})
                facts.setdefault("rx", facts.get("prescribed_strength") or facts.get("prescribed", ""))
                facts.setdefault("bottle", facts.get("dispensed_strength") or facts.get("dispensed", ""))
                facts.setdefault("weight", facts.get("weight_kg", ""))
                if facts.get("unit") in i18n.UNITS:
                    facts["unit"] = i18n.UNITS[facts["unit"]][language]
                if "range" in facts:
                    facts["range"] = _localise_units(str(facts["range"]), language)
                try:
                    parts.append(tpl.format(**facts))
                except KeyError:
                    parts.append(i18n.REASON["_default"][language])
                seen.add(f["type"])
                if audience == "caregiver" and len(parts) >= 2:
                    break
        if not parts:
            parts.append(i18n.REASON["_cannot"][language])
    if audience == "professional":
        ids = [f["rule_id"] for f in verification["findings"] if f["status"] in ("fail", "cannot_evaluate", "out_of_scope") and f.get("severity") != "advisory"]
        if ids:
            parts.append("(" + ", ".join(ids) + ")")
    parts.append(i18n.ACTION[state][language])
    return " ".join(parts)


# Languages in which the audit rejected every planted error and passed every correct text
# (tools/audit_canary.py, benchmarks/results/audit_canary.json). In Swahili, Nemotron 3 Nano did not catch
# a dose said to be "above" the range when it was below, so Swahili readers get the reviewed phrase table.
AUDITED_LANGUAGES = {"en", "fr", "ar"}


def explain(client: ModelClient, verification: dict[str, Any], language: str = "en", audience: str = "caregiver",
            use_model: bool = True) -> dict[str, Any]:
    tokens, items = value_table(verification, language)
    base = {"language": language, "direction": i18n.LANGUAGES[language]["dir"], "audience": audience,
            "state": verification["state"], "state_label": tokens["state"], "action": tokens["action"],
            "result_sha256": verification["result_sha256"]}
    fallback = lambda extra: {**base, "text": deterministic(verification, language, audience), "source": "deterministic", **extra}
    if language not in AUDITED_LANGUAGES:
        return fallback({"note": "The explanation audit did not catch every planted error in this language, so the reviewed phrase table is shown."})
    if not (use_model and client.available("ultra")):
        return fallback({})
    payload: dict[str, Any] = {"action_token": "{{action}}", "findings": items}
    if not items:
        # Nothing failed: give the model the verdict to write about, or it returns the action token alone.
        payload["note"] = ("No rule failed: the medicine, its strength, the dose and the duration match the prescription "
                           "and the guideline. Say this in one or two plain sentences, then write the action token.")
    messages = [
        {"role": "system", "content": SYSTEM.format(language=i18n.LANGUAGES[language]["name"], audience=AUDIENCE[audience])},
        {"role": "user", "content": "Findings (values are placeholder tokens that already include units):\n" + json.dumps(payload, ensure_ascii=False, indent=1)},
    ]
    schema = {"type": "object", "additionalProperties": False, "required": ["text"], "properties": {"text": {"type": "string"}}}
    try:
        res = client.chat("ultra", messages, schema=schema, purpose=f"{PROMPT_VERSION}:{audience}:{language}", max_tokens=700)
        template = str(parse_json(res.content, res.reasoning).get("text", ""))
    except (ModelUnavailable, ValueError) as exc:
        return fallback({"model_error": str(exc)})
    meta = {"model": res.record.model, "provider": res.record.provider, "replayed": res.record.replayed}
    problems = check_integrity(template, tokens, ["action"])
    if problems:
        return fallback({**meta, "model_rejected": {"text": template, "problems": problems}, "integrity": {"ok": False, "problems": problems}})
    text = render(template, tokens)
    audit_result: dict[str, Any] | None = None
    if client.available("structure"):
        try:
            audit_result = audit(client, text, items, verification["state"], audience)
        except (ModelUnavailable, ValueError) as exc:
            return fallback({**meta, "model_rejected": {"text": text, "problems": [f"audit unavailable: {exc}"]}})
        if audit_result["problems"]:
            return fallback({**meta, "model_rejected": {"text": text, "problems": audit_result["problems"]}, "audit": audit_result,
                             "integrity": {"ok": False, "problems": audit_result["problems"]}})
    checks = ["no free digits", "known tokens only", "required tokens present"]
    if audit_result:
        checks.append(f"claims audited by {audit_result['model']}")
    return {**base, **meta, "text": text, "template": template, "source": "model", "audit": audit_result,
            "integrity": {"ok": True, "checks": checks}}
