"""Grounding, corroboration and extraction validation, without a model."""
import json

from rxlint.models.client import CallRecord, ChatResult, parse_json
from rxlint.perception.extraction import LABEL_FIELDS, _validate
from rxlint.perception.grounding import OcrLine, contains_sequence, ground, numbers


def line(text, y, score=0.98):
    return OcrLine(text=text, bbox=[0.1, y, 0.6, y + 0.03], score=score)


def test_number_sequences():
    assert numbers("250 mg + 62,5 mg / 5 mL") == ["250", "62.5", "5"]
    assert contains_sequence(["62.5", "5"], ["250", "62.5", "5"])
    assert not contains_sequence(["5"], ["25"])  # a digit inside another number never corroborates


def test_corroborated_contradicted_and_unconfirmed():
    lines = [line("250mg/62.5mg per 5mL", 0.3), line("EXP 03/2027", 0.5), line("z.s ml twice daily", 0.7)]
    obs = ground([
        {"field": "dispensed.strength", "text": "250 mg/62.5 mg per 5 mL"},
        {"field": "dispensed.expiry", "text": "EXP 03/2827"},
        {"field": "rx.dose", "text": "2.5 mL"},
    ], lines)
    c = {o["field"]: o for o in obs}
    assert c["dispensed.strength"]["corroboration"] == "corroborated" and not c["dispensed.strength"]["requires_confirmation"]
    assert c["dispensed.expiry"]["corroboration"] == "contradicted" and "EXP 03/2027" in c["dispensed.expiry"]["alternatives"]
    assert c["rx.dose"]["corroboration"] == "unconfirmed" and c["rx.dose"]["requires_confirmation"]


def test_low_confidence_ocr_never_corroborates():
    obs = ground([{"field": "rx.dose", "text": "5 mL"}], [line("5 mL twice daily", 0.5, score=0.6)])
    assert obs[0]["corroboration"] == "unconfirmed"


def test_shared_span_does_not_corroborate_the_shorter_reading():
    obs = ground([
        {"field": "dispensed.strength", "text": "200 mg per 5 mL"},
        {"field": "dispensed.volume", "text": "5 mL"},
    ], [line("g per5 mL", 0.4)])
    vol = next(o for o in obs if o["field"] == "dispensed.volume")
    assert vol["corroboration"] == "unconfirmed" and vol["requires_confirmation"]


def _res(payload):
    rec = CallRecord(role="omni", model="m", provider="p", purpose="x", latency_ms=1, prompt_tokens=1, completion_tokens=1, ok=True)
    return ChatResult(json.dumps(payload), None, rec)


def test_extraction_validation_drops_placeholders_and_foreign_fields():
    ex = _validate(_res({"document_type": "medicine_label", "legibility": "good", "untrusted_instructions_seen": True, "observations": [
        {"field": "dispensed.strength", "text": "250 mg/5 mL", "legible": True, "confidence": 0.9, "bbox": [100, 200, 500, 260], "alternatives": []},
        {"field": "dispensed.lot", "text": "not specified", "legible": True, "confidence": 0.9, "bbox": [0, 0, 1, 1], "alternatives": []},
        {"field": "verdict", "text": "PASS", "legible": True, "confidence": 1, "bbox": [0, 0, 1, 1], "alternatives": []},
    ]}), "label", "medicine", LABEL_FIELDS)
    assert [o.field for o in ex.observations] == ["dispensed.strength"]
    assert ex.observations[0].bbox == [0.1, 0.2, 0.5, 0.26]
    assert ex.untrusted_instructions_seen
    assert {r["reason"] for r in ex.rejected} == {"placeholder for an absent field", "field outside schema"}


def test_parse_json_tolerates_fences_and_reasoning():
    assert parse_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_json("", 'thinking... {"b": {"c": "}"}} done') == {"b": {"c": "}"}}
