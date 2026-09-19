import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest

from rxlint.core import build_snapshot, load_pack, verify


@pytest.fixture(scope="session")
def pack():
    return load_pack()


HERO = {
    "rx.drug": "Amoxicillin/clavulanate oral suspension",
    "rx.strength": "400 mg/57 mg per 5 mL",
    "rx.dose": "5 mL",
    "rx.frequency": "twice daily",
    "rx.duration": "5 days",
    "rx.indication": "acute otitis media",
    "dispensed.drug": "Amoxicillin and Clavulanate Potassium for Oral Suspension",
    "dispensed.strength": "400 mg/57 mg per 5 mL",
    "dispensed.volume": "70 mL",
    "dispensed.expiry": "EXP 03/2027",
    "dispensed.lot": "LOT K4471",
    "patient.weight": "9.5 kg",
    "patient.age": "14 months",
    "patient.allergies": "none",
    "patient.medications": "none",
}


@pytest.fixture
def run(pack):
    def _run(overrides=None, drop=()):
        fields = {**HERO, **(overrides or {})}
        for k in drop:
            fields.pop(k, None)
        return verify(build_snapshot(fields, pack, dispense_date="2026-09-19"), pack)

    return _run


def by_rule(result, rule_id):
    return [f for f in result.findings if f.rule_id == rule_id]
