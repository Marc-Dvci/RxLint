"""Regression tests for safety boundaries introduced by the external-review fixes."""
import copy
import io
import json
from datetime import date

import numpy as np
import pytest
from PIL import Image

from rxlint.bench.evaluate import select_threshold
from rxlint.core import EvidenceKind, Normalizer, Observation, SnapshotBuilder, verify
from rxlint.core.units import Unparseable, parse_expiry
from rxlint.fhir import FHIRImportError, import_prescription
from rxlint.models.client import CallRecord, ChatResult
from rxlint.perception import refine
from rxlint.perception.ensemble import merge
from rxlint.perception.extraction import Extraction, RawObservation
from rxlint.perception.grounding import OcrLine, ground


def prescription():
    return {
        "resourceType": "MedicationRequest", "id": "demo-order", "status": "active", "intent": "order",
        "medicationReference": {"reference": "#medicine"},
        "contained": [{"resourceType": "Medication", "id": "medicine",
            "code": {"text": "Amoxicillin/clavulanate"}, "form": {"text": "oral suspension"},
            "ingredient": [
                {"itemCodeableConcept": {"text": "clavulanic acid"}, "strength": {
                    "numerator": {"value": 57, "unit": "mg"}, "denominator": {"value": 5, "unit": "mL"}}},
                {"itemCodeableConcept": {"text": "amoxicillin"}, "strength": {
                    "numerator": {"value": 400, "unit": "mg"}, "denominator": {"value": 5, "unit": "mL"}}}]}],
        "reasonCode": [{"text": "acute otitis media"}],
        "dosageInstruction": [{"doseAndRate": [{"doseQuantity": {"value": 5, "unit": "mL"}}],
            "route": {"text": "oral"}, "timing": {"repeat": {"frequency": 2, "period": 1, "periodUnit": "d",
                "boundsDuration": {"value": 5, "unit": "d"}}}}],
    }


def test_fhir_fixed_order_runs_same_kernel_and_records_source_paths(pack):
    from conftest import HERO
    obs = import_prescription(prescription())
    assert next(o["text"] for o in obs if o["field"] == "rx.strength") == "400 mg/57 mg per 5 mL"
    b = SnapshotBuilder(Normalizer(pack), "fhir-demo")
    for o in obs:
        b.add(Observation(field=o["field"], raw=o["text"], kind=EvidenceKind.STRUCTURED_PRESCRIPTION,
                          method=o["method"], asset_id=o["asset_id"], source_path=o["source_path"]))
    for field, text in HERO.items():
        if field.startswith(("dispensed.", "patient.")):
            b.add(Observation(field=field, raw=text, kind=EvidenceKind.USER_ENTERED_FACT))
    result = verify(b.build(dispense_date=date(2026, 9, 19)), pack)
    assert result.state == "PASS"
    assert any(e["kind"] == EvidenceKind.STRUCTURED_PRESCRIPTION and e["source"]["span"] for e in result.evidence.values())


@pytest.mark.parametrize("change", ["range", "prn", "taper", "conditional", "cancelled", "nonfinite", "unit", "ingredients"])
def test_fhir_rejects_unsupported_or_conflicting_orders(change):
    p = prescription()
    d = p["dosageInstruction"][0]
    if change == "range": d["doseAndRate"][0] = {"doseRange": {"low": {"value": 1, "unit": "mL"}}}
    if change == "prn": d["asNeededBoolean"] = True
    if change == "taper": p["dosageInstruction"].append(copy.deepcopy(d))
    if change == "conditional": d["timing"]["repeat"]["dayOfWeek"] = ["mon"]
    if change == "cancelled": p["status"] = "cancelled"
    if change == "nonfinite": d["doseAndRate"][0]["doseQuantity"]["value"] = "NaN"
    if change == "unit": d["doseAndRate"][0]["doseQuantity"]["code"] = "mg"
    if change == "ingredients": p["contained"][0]["ingredient"][0]["itemCodeableConcept"]["text"] = "trimethoprim"
    with pytest.raises(FHIRImportError): import_prescription(p)


def test_fhir_bundle_local_reference_and_no_missing_field_inference():
    p = prescription()
    med = p.pop("contained")[0]
    p["medicationReference"]["reference"] = "Medication/medicine"
    del p["dosageInstruction"][0]["timing"]["repeat"]["boundsDuration"]
    obs = import_prescription({"resourceType": "Bundle", "entry": [{"resource": p}, {"resource": med}]})
    assert not any(o["field"] == "rx.duration" for o in obs)
    assert all(o["source_path"].startswith("$.entry[0].resource") for o in obs)


def test_threshold_is_case_independent_and_never_splits_tied_scores():
    t, selected = select_threshold(np.array([.7, .8, .9, .9, 1.]), np.array([0, 1, 0, 1, 1]), 0)
    assert .9 < t <= 1 and selected["false_accepts"] == 0 and selected["accepted_correct"] == 1
    t, selected = select_threshold(np.array([1., 1.]), np.array([0, 1]), 0)
    assert t > 1 and selected["accepted_correct"] == 0


def test_expiry_day_is_not_silently_discarded():
    assert parse_expiry("EXP 31/12/2027") == date(2027, 12, 31)
    assert parse_expiry("EXP 2027-03-04") == date(2027, 3, 4)
    assert parse_expiry("EXP March 2027") == date(2027, 3, 31)
    for text in ("EXP 03/04/2027", "EXP 03/2027 or 04/2027", "EXP 32/12/2027", "EXP 13/2027"):
        with pytest.raises(Unparseable): parse_expiry(text)


def test_ocr_recovery_does_not_corroborate_itself():
    lines = [OcrLine("EXP 03/2027", [.1, .1, .8, .15], .99)]
    obs = refine.validate(ground(refine.recover([], lines, "medicine"), lines))
    assert obs[0]["requires_confirmation"] and obs[0]["single_reader_recovery"]


def test_ambiguous_ocr_recovery_preserves_existing_alternatives():
    obs = [{"field": "dispensed.expiry", "text": "EXP 03/2027", "alternatives": ["EXP 03/2028"]}]
    assert refine.recover(obs, [OcrLine("EXP 03/2027", [.1,.1,.8,.15], .99)], "medicine") == obs


def test_crop_read_must_agree_with_independent_ocr_and_preserve_ambiguity():
    class Reader:
        def chat(self, *args, **kwargs):
            rec = CallRecord("vision", "test", "test", "crop", 1, 1, 1, True)
            return ChatResult(json.dumps({"text": "5 mL", "legible": True, "alternatives": []}), None, rec)
    b = io.BytesIO(); Image.new("RGB", (400, 300), "white").save(b, "PNG")
    base = {"field": "rx.dose", "text": "6 mL", "ocr_text": "5 mL", "ocr_score": .99,
            "bbox": [.1,.1,.8,.2], "legible": True, "corroboration": "contradicted", "alternatives": ["5 mL"]}
    good = refine.resolve([base], b.getvalue(), Reader())[0]
    assert good["text"] == "5 mL" and good["original_reading"] == "6 mL"
    bad = refine.resolve([{**base, "ocr_text": "7 mL"}], b.getvalue(), Reader())[0]
    assert bad["text"] == "6 mL"
    ambiguous = {**base, "alternatives": ["5 mL", "8 mL"]}
    assert refine.resolve([ambiguous], b.getvalue(), Reader())[0]["alternatives"] == ["5 mL", "8 mL"]


def test_dual_readers_cannot_vote_away_disagreement():
    def ex(text):
        return Extraction(asset_id="rx", kind="prescription", observations=[RawObservation(field="rx.dose", text=text)])
    agreed = merge(ex("2,5 mL"), ex("2.5 mL"))
    assert agreed.reader_agreement["rx.dose"] == "dual_agreement"
    disputed = merge(ex("2.5 mL"), ex("7.5 mL"))
    assert disputed.observations[0].alternatives == ["7.5 mL"]
    assert ground([agreed.observations[0].model_dump()], [])[0]["requires_confirmation"]


def test_cassette_keys_separate_models_without_breaking_legacy_replay():
    from rxlint.models.client import _request_key
    messages = [{"role": "user", "content": "same input"}]
    assert _request_key("vision", "a", messages, None, "read") != _request_key("vision", "b", messages, None, "read")
    assert _request_key("vision", "a", messages, None, "read", legacy=True) == _request_key("vision", "b", messages, None, "read", legacy=True)
    assert _request_key("vision", "a", messages, None, "read", settings={"max_tokens": 300}) != _request_key("vision", "a", messages, None, "read", settings={"max_tokens": 500})


def test_duplicate_machine_reader_cannot_waive_reliability_veto(pack):
    b = SnapshotBuilder(Normalizer(pack), "veto")
    b.add(Observation(field="rx.dose", raw="5 mL", requires_confirmation=True, method="reader-a"))
    b.add(Observation(field="rx.dose", raw="5 mL", method="reader-b"))
    assert b.build().fact("rx.dose").status == "ambiguous"


def test_trademark_normalization_keeps_brand_word_boundary(pack):
    n = Normalizer(pack)
    assert n.product("Amoxil™").value == "amoxicillin"
    assert n.product("Augmentin®").value == "amoxicillin+clavulanic_acid"


def test_expiry_whitespace_format_retains_exact_month():
    assert parse_expiry("EXP 11 2012") == date(2012, 11, 30)


def test_ocr_failure_cannot_silently_accept_high_risk_model_readings():
    from rxlint.pipeline import _obs_from_extraction
    ex = Extraction(asset_id="rx", kind="prescription", observations=[RawObservation(field="rx.dose", text="5 mL")])
    assert _obs_from_extraction(ex, None)[0]["requires_confirmation"] is True


def test_transcript_recovery_copies_unique_concentrations_and_preserves_disputes():
    from rxlint.perception.transcribe import recover_transcript_fields, clean_transcript
    lines = ["Amoxil", "125 mg/5 mL", "100 mL"]
    recovered = recover_transcript_fields([], lines, "medicine")
    assert {o.field: o.text for o in recovered} == {"dispensed.drug": "Amoxil", "dispensed.strength": "125 mg/5 mL"}
    assert not recover_transcript_fields([], ["125 mg/5 mL", "250 mg/5 mL"], "medicine")
    assert not recover_transcript_fields([], ["125 mg", "100 mL", "[125|250] mg/5 mL"], "medicine")
    disputed = [RawObservation(field="dispensed.strength", text="125 mg/5 mL", alternatives=["250 mg/5 mL"])]
    assert recover_transcript_fields(disputed, ["250 mg/5 mL"], "medicine") == disputed
    assert clean_transcript(["LOT A1"]*2 + ["SANDOZ"]*30 + ["125 mg/5 mL"]) == ["LOT A1"]*2 + ["SANDOZ"]*2 + ["125 mg/5 mL"]


@pytest.mark.parametrize("change", ["text", "limit", "modifier", "dose_type", "malformed", "choice"])
def test_fhir_never_silently_discards_dosage_conditions(change):
    p = prescription()
    d = p["dosageInstruction"][0]
    if change == "text": d["text"] = "Reduce to once daily after three days"
    if change == "limit": d["maxDosePerAdministration"] = {"value": 2, "unit": "mL"}
    if change == "modifier": d["modifierExtension"] = [{"url": "https://example.org/condition", "valueBoolean": True}]
    if change == "dose_type": d["doseAndRate"][0]["type"] = {"text": "maximum"}
    if change == "malformed": d["timing"] = None
    if change == "choice": p["medicationCodeableConcept"] = {"text": "Cephalexin"}
    with pytest.raises(FHIRImportError): import_prescription(p)


def test_partial_ingredient_line_cannot_hide_combination_evidence(pack):
    n = Normalizer(pack)
    assert n.product("Amoxycillin 500 mg +").status == "unresolved"
    obs = [{"field": "dispensed.drug", "text": "Amoxicillin 250 mg"}]
    audited = refine.validate_products(obs, ["Amoxicillin. trihydric. - Kal. clavulan."], "medicine")
    assert audited[0]["requires_confirmation"] and audited[0]["alternatives"]
    assert refine.validate_products(obs, ["Amoxicillin 250 mg/5 mL", "100 mL"], "medicine") == obs
    combination = [{"field": "dispensed.drug", "text": "Amoxicillin/clavulanate"}]
    assert refine.validate_products(combination, ["Amoxicillin 250 mg", "Clavulanic acid 62.5 mg"], "medicine") == combination
    incomplete = [*obs, {"field": "dispensed.strength", "text": "250 mg/5 mL"}]
    assert refine.validate_products(incomplete, ["Amoxicillin. trihydric. - Kal. clavulan."], "medicine")[1]["requires_confirmation"]


def test_incomplete_fold_cannot_be_used_for_calibration_or_published_summary():
    from rxlint.bench.evaluate import require_complete_folds
    manifest = [{"case_id": "a", "split": "test"}, {"case_id": "b", "split": "test"}]
    with pytest.raises(ValueError, match="incomplete"): require_complete_folds(manifest[:1], manifest, ("test",))
    require_complete_folds(manifest, manifest, ("test",))
