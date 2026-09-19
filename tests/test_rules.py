"""Boundary tests for every rule family (spec section 27)."""
import pytest

from conftest import by_rule

AMOX_TID = {
    "rx.drug": "Amoxicillin oral suspension", "rx.strength": "250 mg/5 mL", "rx.frequency": "three times a day",
    "dispensed.drug": "Amoxicillin for oral suspension", "dispensed.strength": "250 mg/5 mL",
    "patient.weight": "7 kg", "dispensed.volume": "150 mL",
}


def amox(run, volume, drop=(), **extra):
    over = {**AMOX_TID, "rx.dose": f"{volume} mL", **extra}
    return run(over, drop=("rx.indication", *drop))


# mg/kg/day = V x 50 x 3 / 7. The tolerated range is 80-90 +/-10% = 72-99 (policy P-ROUND-01).
@pytest.mark.parametrize("volume,status,severity", [
    ("3.3", "fail", "high"),       # 70.71 below the tolerated lower bound
    ("3.36", "pass", None),        # 72.00 exact tolerated lower bound
    ("3.9", "pass", None),         # 83.57 inside
    ("4.62", "pass", None),        # 99.00 exact tolerated upper bound
    ("4.7", "fail", "high"),       # 100.71 above
    ("8.3", "fail", "high"),       # 177.86 just under 2x the upper bound
    ("8.4", "fail", "critical"),   # 180.00 = 2x upper bound (P-SEV-01)
    ("1.8", "fail", "critical"),   # 38.57 below half the lower bound
])
def test_amoxicillin_daily_dose_boundaries(run, volume, status, severity):
    f = by_rule(amox(run, volume), "AWARE-AMX-PED-001")[0]
    assert (f.status, f.severity) == (status, severity)


def test_dose_rule_missing_weight_cannot_verify(run):
    r = amox(run, "3.9", drop=("patient.weight",))
    f = by_rule(r, "AWARE-AMX-PED-001")[0]
    assert f.status == "cannot_evaluate" and f.action == "REQUEST_WEIGHT"
    assert r.state == "CANNOT_VERIFY"


def test_dose_rule_out_of_scope_age(run):
    r = amox(run, "3.9", **{"patient.age": "13 years", "patient.weight": "40 kg"})
    assert r.state == "OUT_OF_SCOPE"
    assert by_rule(r, "AWARE-AMX-PED-001")[0].status == "not_applicable"


def test_unit_conversion_is_outcome_neutral(run):
    a = amox(run, "3.9")
    b = amox(run, "3.9", **{"dispensed.strength": "0.25 g/5 mL", "rx.strength": "50 mg/mL"})
    outcome = lambda r: (r.state, [(f.rule_id, f.status, f.severity, f.facts.get("value")) for f in r.findings])
    assert outcome(a) == outcome(b)


def test_weight_band_passes(run):
    # 12 kg, 500 mg every 12 hours from 400 mg/5 mL = 6.25 mL: the 10-<15 kg band dose.
    r = run({"patient.weight": "12 kg", "rx.dose": "6.25 mL", "dispensed.volume": "100 mL"})
    f = by_rule(r, "AWARE-AMC-PED-001")[0]
    assert f.status == "pass" and "weight band" in f.message


def test_weight_band_only(run):
    # 14.5 kg on 500 mg q12h is 69 mg/kg/day (below 72) but equals the 10-<15 kg band dose.
    r = run({"patient.weight": "14.5 kg", "rx.dose": "6.25 mL", "dispensed.volume": "100 mL"})
    assert by_rule(r, "AWARE-AMC-PED-001")[0].status == "pass"


CFX = {"rx.drug": "Cefalexin oral suspension", "rx.strength": "250 mg/5 mL", "dispensed.drug": "Cefalexin",
       "dispensed.strength": "250 mg/5 mL", "rx.indication": "pharyngitis", "patient.weight": "32 kg",
       "patient.age": "10 years", "dispensed.volume": "200 mL"}


def test_cefalexin_adult_dose_above_30kg(run):
    ok = run({**CFX, "rx.dose": "10 mL", "rx.frequency": "every 8 hours"})
    assert by_rule(ok, "AWARE-CFX-PED-001")[0].status == "pass"
    low = run({**CFX, "rx.dose": "5 mL", "rx.frequency": "every 8 hours"})
    assert by_rule(low, "AWARE-CFX-PED-001")[0].status == "fail"


AZM = {"rx.drug": "Azithromycin oral suspension", "rx.strength": "200 mg/5 mL", "dispensed.drug": "Azithromycin",
       "dispensed.strength": "200 mg/5 mL", "rx.frequency": "once daily", "rx.duration": "3 days", "patient.weight": "15 kg"}


def test_azithromycin_discrete_options_and_max(run):
    ten = run({**AZM, "rx.dose": "3.75 mL"}, drop=("rx.indication",))  # 150 mg = 10 mg/kg
    assert by_rule(ten, "AWARE-AZM-PED-001")[0].status == "pass"
    mid = run({**AZM, "rx.dose": "5.6 mL"}, drop=("rx.indication",))  # 224 mg = 14.9 mg/kg
    assert by_rule(mid, "AWARE-AZM-PED-001")[0].status == "fail"
    big = run({**AZM, "rx.dose": "15 mL", "patient.weight": "30 kg"}, drop=("rx.indication",))
    assert by_rule(big, "AWARE-AZM-PED-002")[0].status == "fail"  # 600 mg > 500 mg


def test_amoxicillin_max_daily_is_advisory(run):
    r = run({"rx.drug": "Amoxicillin", "rx.strength": "400 mg/5 mL", "dispensed.drug": "Amoxicillin",
             "dispensed.strength": "400 mg/5 mL", "rx.dose": "12.5 mL", "rx.frequency": "every 12 hours",
             "patient.weight": "22 kg", "patient.age": "7 years", "dispensed.volume": "150 mL"})
    note = by_rule(r, "AWARE-AMX-PED-002")[0]
    assert note.status == "fail" and note.severity == "advisory"
    assert r.state == "PASS"  # 1 g every 12 hours is the WHO >= 20 kg band


def test_frequency_rule(run):
    r = run({"rx.frequency": "three times a day", "dispensed.volume": "100 mL"})
    assert by_rule(r, "AWARE-AMC-PED-003")[0].status == "fail"


@pytest.mark.parametrize("days,status", [("5 days", "pass"), ("7 days", "fail"), ("10 days", "fail")])
def test_duration_aom(run, days, status):
    r = run({"rx.duration": days, "dispensed.volume": "150 mL"})
    assert by_rule(r, "AWARE-DUR-AOM")[0].status == status


def test_duration_skipped_without_indication(run):
    r = run(drop=("rx.indication",))
    assert not by_rule(r, "AWARE-DUR-AOM")
    assert r.state == "PASS"


def test_duration_range_uti(run):
    r = run({"rx.indication": "cystitis", "rx.duration": "4 days"})
    assert by_rule(r, "AWARE-DUR-UTI")[0].status == "pass"


@pytest.mark.parametrize("allergy,rule,expect_state", [
    ("penicillin", "RX-ALLERGY-001", "REVIEW"),
    ("Pénicilline", "RX-ALLERGY-001", "REVIEW"),
    ("amoxicillin rash", "RX-ALLERGY-001", "REVIEW"),
    ("cephalosporins", "RX-ALLERGY-004", "REVIEW"),
    ("peanuts", None, "PASS"),
    ("NKDA", None, "PASS"),
    ("no penicillin allergy", "RX-ALLERGY-000", "CANNOT_VERIFY"),
    ("the pink one", "RX-ALLERGY-000", "CANNOT_VERIFY"),
])
def test_allergies(run, allergy, rule, expect_state):
    r = run({"patient.allergies": allergy})
    assert r.state == expect_state
    if rule:
        assert by_rule(r, rule)[0].status in ("fail", "cannot_evaluate")


def test_cephalosporin_cross_sensitivity(run):
    r = run({"rx.drug": "Cefalexin", "rx.strength": "250 mg/5 mL", "dispensed.drug": "Cefalexin",
             "dispensed.strength": "250 mg/5 mL", "rx.dose": "5 mL", "rx.indication": "pharyngitis",
             "patient.allergies": "penicillin"})
    f = by_rule(r, "RX-ALLERGY-003")[0]
    assert f.status == "fail" and f.severity == "high"


def test_cotrimoxazole_under_two_months(run):
    r = run({"rx.drug": "Co-trimoxazole", "rx.strength": "200 mg/40 mg per 5 mL",
             "dispensed.drug": "Sulfamethoxazole and Trimethoprim Oral Suspension",
             "dispensed.strength": "200 mg/40 mg per 5 mL", "rx.dose": "1.5 mL", "patient.weight": "3.8 kg",
             "patient.age": "5 weeks"}, drop=("rx.indication",))
    assert by_rule(r, "RX-SXT-AGE-001")[0].status == "fail"


@pytest.mark.parametrize("meds,rule", [
    ("warfarin", "DDI-AMX-002"), ("probenecid", "DDI-AMX-001"), ("Augmentin", "RX-DUP-001"),
    ("amoxicillin", "RX-DUP-001"), ("penicillin V", "RX-DUP-002"),
])
def test_interactions_and_duplicates(run, meds, rule):
    r = run({"patient.medications": meds})
    assert by_rule(r, rule)[0].status == "fail"


def test_interaction_coverage_is_reported(run):
    r = run({"patient.medications": "paracetamol, salbutamol"})
    assert r.state == "PASS"
    assert r.coverage["current_medicines_not_covered"] == ["paracetamol", "salbutamol"]


def test_unrecognised_medicine_blocks_pass(run):
    r = run({"patient.medications": "the blue inhaler"})
    assert r.state == "CANNOT_VERIFY"


def test_expiry_and_course_end(run):
    assert run({"dispensed.expiry": "EXP 08/2026"}).state == "REVIEW"
    r = run({"dispensed.expiry": "2026-09-21"})
    f = by_rule(r, "RX-PRODUCT-005")[0]
    assert f.status == "fail" and f.severity == "moderate"


def test_quantity(run):
    r = run({"dispensed.volume": "35 mL"})  # course needs 5 x 2 x 5 = 50 mL
    assert by_rule(r, "RX-PRODUCT-006")[0].status == "fail"


def test_volume_without_concentration_cannot_verify(run):
    r = run(drop=("rx.strength",))
    assert r.state == "CANNOT_VERIFY"
    assert by_rule(r, "RX-PRODUCT-004")[0].action == "REQUEST_FIELD_CONFIRMATION"


def test_dosage_form_mismatch(run):
    r = run({"dispensed.drug": "Amoxicillin/clavulanate 500/125 mg tablets", "dispensed.strength": "500 mg/125 mg tablet"})
    assert by_rule(r, "RX-PRODUCT-002")[0].status == "fail"


def test_non_oral_route_out_of_scope(run):
    r = run({"rx.route": "IV"})
    assert r.state == "OUT_OF_SCOPE"
