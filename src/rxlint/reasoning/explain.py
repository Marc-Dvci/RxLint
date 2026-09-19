"""Explanations of established findings, for professionals and for caregivers.

Nemotron 3 Ultra writes connective prose around placeholder tokens such as ``{{v1}}``. The values
behind the tokens (numbers, drug names, units, the verdict and the action with its negation)
come from the verification object and the deterministic phrase table. Before a model text is
shown, an integrity check proves it has no free-standing digits, uses only known tokens, and
contains every required token; otherwise the deterministic template is used.
"""

from __future__ import annotations

import re
from typing import Any

from ..models.client import ModelClient, ModelUnavailable, parse_json
from . import i18n

TOKEN = re.compile(r"\{\{([a-z0-9_]+)\}\}")
PROMPT_VERSION = "explain-v2"

SYSTEM = """You explain the result of a deterministic medication check. The check is already complete; you cannot change it.
Write in {language}. Use the placeholder tokens given (for example {{{{v1}}}}) wherever a value, a medicine name or the action is needed.
Never write a digit yourself: every number must come through a token. Never add a clinical recommendation, a new dose, or a fact that is not in the findings.
{audience}
Reply with one JSON object: {{"text": "..."}}."""

AUDIENCE = {
    "professional": "The reader is a pharmacist. Be precise and brief: at most four sentences. Name the rule identifiers given.",
    "caregiver": "The reader is a parent or caregiver. Use plain words, at most three short sentences. Do not mention rule identifiers. The action token {{action}} must appear exactly once, as the last sentence.",
}


def _fmt_value(v: Any) -> str:
    return str(v)


def value_table(verification: dict[str, Any], language: str) -> tuple[dict[str, str], list[dict[str, Any]]]:
    """Tokens for every value a failing finding carries, plus the verdict and action phrases."""
    state = verification["state"]
    tokens: dict[str, str] = {
        "state": i18n.STATE[state][language],
        "action": i18n.ACTION[state][language],
    }
    items = []
    n = 0
    for f in verification["findings"]:
        if f["status"] not in ("fail", "cannot_evaluate", "out_of_scope"):
            continue
        if f["status"] == "fail" and f.get("severity") == "advisory":
            continue
        entry = {"rule_id": f["rule_id"], "title": f["title"], "status": f["status"], "severity": f.get("severity"), "values": {}}
        for k, v in (f.get("facts") or {}).items():
            if isinstance(v, (list, dict)):
                continue
            n += 1
            key = f"v{n}"
            val = _fmt_value(v)
            if k == "unit" and v in i18n.UNITS:
                val = i18n.UNITS[v][language]
            tokens[key] = val
            entry["values"][k] = "{{" + key + "}}"
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
                if facts.get("unit") in i18n.UNITS:
                    facts["unit"] = i18n.UNITS[facts["unit"]][language]
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


def explain(client: ModelClient, verification: dict[str, Any], language: str = "en", audience: str = "caregiver",
            use_model: bool = True) -> dict[str, Any]:
    tokens, items = value_table(verification, language)
    base = {"language": language, "direction": i18n.LANGUAGES[language]["dir"], "audience": audience,
            "state": verification["state"], "state_label": tokens["state"], "action": tokens["action"],
            "result_sha256": verification["result_sha256"]}
    if use_model and client.available("ultra"):
        payload = {"verdict_token": "{{state}}", "action_token": "{{action}}", "findings": items}
        messages = [
            {"role": "system", "content": SYSTEM.format(language=i18n.LANGUAGES[language]["name"], audience=AUDIENCE[audience])},
            {"role": "user", "content": "Findings (values are placeholder tokens):\n" + _json(payload)},
        ]
        schema = {"type": "object", "additionalProperties": False, "required": ["text"], "properties": {"text": {"type": "string"}}}
        try:
            res = client.chat("ultra", messages, schema=schema, purpose=f"{PROMPT_VERSION}:{audience}:{language}", max_tokens=700)
            text = str(parse_json(res.content, res.reasoning).get("text", ""))
            required = ["action"] if audience == "caregiver" else []
            problems = check_integrity(text, tokens, required)
            if not problems:
                return {**base, "text": render(text, tokens), "template": text, "source": "model",
                        "model": res.record.model, "provider": res.record.provider, "replayed": res.record.replayed,
                        "integrity": {"ok": True, "checks": ["no free digits", "known tokens only", "required tokens present"]}}
            fallback = deterministic(verification, language, audience)
            return {**base, "text": fallback, "source": "deterministic", "model_rejected": {"text": text, "problems": problems},
                    "model": res.record.model, "provider": res.record.provider,
                    "integrity": {"ok": False, "problems": problems}}
        except (ModelUnavailable, ValueError) as exc:
            return {**base, "text": deterministic(verification, language, audience), "source": "deterministic",
                    "model_error": str(exc)}
    return {**base, "text": deterministic(verification, language, audience), "source": "deterministic"}


def _json(o: Any) -> str:
    import json

    return json.dumps(o, ensure_ascii=False, indent=1)
