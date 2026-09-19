"""Smallest clarification that unlocks the deterministic checker.

The kernel already names the missing or contradictory facts. Nemotron 3 Ultra looks at the
evidence around them (competing readings, OCR disagreement, image-quality flags) and picks one
action from a closed set, with a one-sentence instruction for the pharmacist. The choice is
validated: the action must be in the set, the fields must be among the blocked ones, and the
message may only repeat numbers that already appear in the evidence.
"""

from __future__ import annotations

import json
import re
from typing import Any

from ..models.client import ModelClient, ModelUnavailable, parse_json

ACTIONS = [
    "REQUEST_NEW_PHOTO",
    "REQUEST_FIELD_CONFIRMATION",
    "REQUEST_WEIGHT",
    "REQUEST_AGE",
    "REQUEST_INDICATION",
    "REQUEST_ALLERGY_CONFIRMATION",
    "REQUEST_MEDICATION_LIST",
    "NO_CLARIFICATION_NEEDED",
]

TEMPLATES = {
    "REQUEST_NEW_PHOTO": "Retake the photo of {where} so that {fields} can be read clearly.",
    "REQUEST_FIELD_CONFIRMATION": "Confirm {fields} with the prescriber or from the original document.",
    "REQUEST_WEIGHT": "Enter the child's current weight in kilograms.",
    "REQUEST_AGE": "Enter the child's age.",
    "REQUEST_INDICATION": "Enter the indication written by the prescriber.",
    "REQUEST_ALLERGY_CONFIRMATION": "Confirm the allergy history: {fields}.",
    "REQUEST_MEDICATION_LIST": "List the child's current medicines by active ingredient.",
    "NO_CLARIFICATION_NEEDED": "No clarification needed.",
}

FIELD_WORDS = {
    "rx.dose": "the dose on the prescription", "rx.strength": "the strength on the prescription",
    "rx.frequency": "the frequency on the prescription", "rx.duration_days": "the treatment duration",
    "rx.product": "the medicine name on the prescription", "dispensed.product": "the product name on the label",
    "dispensed.strength": "the strength on the label", "dispensed.expiry": "the expiry date on the label",
    "patient.weight_kg": "the child's weight", "patient.age_months": "the child's age",
    "patient.allergies": "the allergy history", "patient.current_medications": "the current medicines",
}

SYSTEM = """You help a pharmacist unblock a deterministic medication check. The checker could not evaluate some rules because evidence is missing, unreadable or contradictory.
Choose the single smallest action that would let the checker continue, from this closed list: {actions}.
Write one short instruction to the pharmacist (at most 30 words). Do not state any clinical conclusion, dose or diagnosis. Only mention numbers that appear in the evidence you are given.
Reply with JSON: {{"action": "...", "fields": ["..."], "message": "..."}}"""


def deterministic_clarification(blocked: list[str], default_action: str) -> dict[str, Any]:
    where = "the prescription" if any(f.startswith("rx.") for f in blocked) else "the medicine label"
    words = ", ".join(FIELD_WORDS.get(f, f) for f in blocked) or "the flagged fields"
    return {"action": default_action, "fields": blocked,
            "message": TEMPLATES[default_action].format(where=where, fields=words), "source": "deterministic"}


def clarify(client: ModelClient, verification, observations: list[dict[str, Any]], quality: dict[str, Any]) -> dict[str, Any]:
    base = verification.clarification or {}
    blocked = base.get("fields", [])
    fallback = deterministic_clarification(blocked, base.get("action", "REQUEST_FIELD_CONFIRMATION"))
    if not blocked or not client.available("ultra"):
        return fallback
    field_prefixes = {f.split(".")[0] for f in blocked}
    evidence = {
        "blocked_facts": {k: {"status": verification.evidence.get(f"ev_{k.replace('.', '_')}", {}).get("status"),
                              "notes": verification.evidence.get(f"ev_{k.replace('.', '_')}", {}).get("notes", [])} for k in blocked},
        "readings": [
            {k: o.get(k) for k in ("field", "text", "legible", "confidence", "alternatives", "corroboration", "ocr_text", "asset_id")}
            for o in observations if o.get("field", "").split(".")[0] in field_prefixes or o.get("field", "").startswith("rx.patient")
        ][:24],
        "image_quality": {a: [c for c in q.get("checks", []) if not c["ok"]] for a, q in quality.items()},
        "kernel_default": base.get("action"),
    }
    messages = [
        {"role": "system", "content": SYSTEM.format(actions=", ".join(ACTIONS))},
        {"role": "user", "content": json.dumps(evidence, ensure_ascii=False, default=str)},
    ]
    schema = {"type": "object", "additionalProperties": False, "required": ["action", "fields", "message"],
              "properties": {"action": {"type": "string", "enum": ACTIONS}, "fields": {"type": "array", "items": {"type": "string"}},
                             "message": {"type": "string"}}}
    try:
        res = client.chat("ultra", messages, schema=schema, purpose="clarify-v1", max_tokens=400)
        data = parse_json(res.content, res.reasoning)
    except (ModelUnavailable, ValueError) as exc:
        return {**fallback, "model_error": str(exc)}
    action = data.get("action")
    fields = [f for f in data.get("fields", []) if f in blocked] or blocked
    message = str(data.get("message", "")).strip()
    evidence_text = json.dumps(evidence, ensure_ascii=False, default=str)
    stray = [n for n in re.findall(r"\d+(?:[.,]\d+)?", message) if n not in evidence_text]
    problems = []
    if action not in ACTIONS or action == "NO_CLARIFICATION_NEEDED":
        problems.append(f"action {action!r} not allowed")
    if stray:
        problems.append(f"numbers not in evidence: {stray}")
    if not message or len(message.split()) > 40:
        problems.append("message missing or too long")
    if problems:
        return {**fallback, "model_rejected": {"output": data, "problems": problems}, "model": res.record.model}
    return {"action": action, "fields": fields, "message": message, "source": "model", "model": res.record.model,
            "provider": res.record.provider, "replayed": res.record.replayed, "kernel_default": base.get("action")}
