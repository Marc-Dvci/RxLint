"""Explanation integrity and clarification validation, with a scripted model."""
import json

from conftest import HERO
from rxlint.core import build_snapshot, verify
from rxlint.models.client import CallRecord, ChatResult, ModelClient
from rxlint.reasoning.clarify import clarify
from rxlint.reasoning.explain import check_integrity, deterministic, explain, value_table


class Scripted(ModelClient):
    def __init__(self, replies):
        super().__init__(mode="live")
        self.replies = list(replies)

    def available(self, role):
        return True

    def chat(self, role, messages, **kw):
        rec = CallRecord(role=role, model="scripted", provider="test", purpose=kw.get("purpose", ""), latency_ms=1,
                         prompt_tokens=None, completion_tokens=None, ok=True)
        self.log.append(rec)
        return ChatResult(self.replies.pop(0), None, rec)


def mismatch(pack):
    return verify(build_snapshot({**HERO, "dispensed.strength": "250 mg/62.5 mg per 5 mL"}, pack, dispense_date="2026-09-19"), pack)


def test_integrity_rejects_free_digits():
    tokens = {"action": "x", "v1": "400"}
    assert check_integrity("The bottle holds 250 mg. {{action}}", tokens, ["action"])
    assert not check_integrity("The strength differs ({{v1}}). {{action}}", tokens, ["action"])
    assert check_integrity("{{v9}} {{action}}", tokens, ["action"])
    assert check_integrity("No action here", tokens, ["action"])
    assert check_integrity("Arabic-Indic digits ٤٠٠ {{action}}", tokens, ["action"])


def test_model_explanation_is_rendered_from_tokens(pack):
    v = mismatch(pack).model_dump()
    tokens, _ = value_table(v, "fr")
    key = next(k for k, val in tokens.items() if val.startswith("400"))
    reply = json.dumps({"text": f"Le dosage prescrit ({{{{{key}}}}}) ne correspond pas au flacon. {{{{action}}}}"})
    audit_ok = json.dumps({"answers": {"strength_mismatch": "differ", "dose_below_range": "not_stated", "problem": "yes", "instruction": "do_not_give_yet"}})
    out = explain(Scripted([reply, audit_ok]), v, "fr", "caregiver")
    assert out["source"] == "model"
    assert "400 mg / 57 mg per 5 mL" in out["text"]
    assert out["text"].endswith("vérifié.")


def test_model_explanation_with_a_number_falls_back(pack):
    v = mismatch(pack).model_dump()
    reply = json.dumps({"text": "Give 7.5 mL instead. {{action}}"})
    out = explain(Scripted([reply]), v, "en", "caregiver")
    assert out["source"] == "deterministic"
    assert "free-standing digit" in out["model_rejected"]["problems"][0]
    assert "7.5" not in out["text"]


def test_deterministic_explanations_in_every_language(pack):
    v = mismatch(pack).model_dump()
    for lang in ("en", "fr", "ar", "sw"):
        text = deterministic(v, lang, "caregiver")
        assert "400" in text and "250" in text


def test_clarification_rejects_invented_numbers(pack):
    r = verify(build_snapshot({k: v for k, v in HERO.items() if k != "patient.weight"}, pack, dispense_date="2026-09-19"), pack)
    bad = Scripted([json.dumps({"action": "REQUEST_WEIGHT", "fields": ["patient.weight_kg"], "message": "The child probably weighs 12 kg."})])
    out = clarify(bad, r, [], {})
    assert out["source"] == "deterministic" and out["model_rejected"]
    good = Scripted([json.dumps({"action": "REQUEST_WEIGHT", "fields": ["patient.weight_kg"], "message": "Weigh the child and enter the weight in kilograms."})])
    out = clarify(good, r, [], {})
    assert out["source"] == "model" and out["action"] == "REQUEST_WEIGHT"


def test_clarification_cannot_pick_no_action(pack):
    r = verify(build_snapshot({k: v for k, v in HERO.items() if k != "patient.weight"}, pack, dispense_date="2026-09-19"), pack)
    out = clarify(Scripted([json.dumps({"action": "NO_CLARIFICATION_NEEDED", "fields": [], "message": "All good."})]), r, [], {})
    assert out["source"] == "deterministic"


def test_audit_rejects_a_reversed_direction(pack):
    """The Arabic text that once said the dose exceeds the limit, when the kernel found it below."""
    v = mismatch(pack).model_dump()
    tokens, _ = value_table(v, "ar")
    reply = json.dumps({"text": "{{v3}} تتجاوز الحد المسموح. {{action}}"})
    audit_bad = json.dumps({"answers": {"strength_mismatch": "not_stated", "dose_below_range": "too_high", "problem": "yes", "instruction": "do_not_give_yet"}})
    out = explain(Scripted([reply, audit_bad]), v, "ar", "caregiver")
    assert out["source"] == "deterministic"
    assert any("dose_below_range" in p for p in out["model_rejected"]["problems"])


def test_deterministic_weight_template_uses_the_weight(pack):
    from conftest import HERO

    v = verify(build_snapshot({**HERO, "rx.dose": "10 mL", "dispensed.volume": "150 mL"}, pack, dispense_date="2026-09-19"), pack).model_dump()
    text = deterministic(v, "en", "caregiver")
    assert "9.5 kg" in text and "168.42" in text
