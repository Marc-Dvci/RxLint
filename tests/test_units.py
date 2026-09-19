from datetime import date
from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from rxlint.core.units import (
    Unparseable, parse_age_months, parse_dose, parse_duration_days, parse_expiry, parse_frequency, parse_lot,
    parse_strength, parse_volume_ml, parse_weight_kg,
)


@pytest.mark.parametrize("raw,comps,per", [
    ("250 mg/5 mL", ["250"], "5"),
    ("250mg/5ml", ["250"], "5"),
    ("400 mg/57 mg per 5 mL", ["400", "57"], "5"),
    ("400/57 mg/5 mL", ["400", "57"], "5"),
    ("250 mg + 62.5 mg / 5 mL", ["250", "62.5"], "5"),
    ("250 mg + 62,5 mg / 5 mL", ["250", "62.5"], "5"),
    ("0.25 g/5 mL", ["250"], "5"),
    ("50 mg/mL", ["50"], "1"),
    ("200 mg/40 mg per 5 mL", ["200", "40"], "5"),
    ("400 mg/57 mg pour 5 ml", ["400", "57"], "5"),
])
def test_strength_liquid(raw, comps, per):
    s = parse_strength(raw)
    assert [str(c) for c in s.components_mg] == comps
    assert str(s.per_ml) == per


def test_strength_solid():
    s = parse_strength("500 mg tablet")
    assert s.per_unit == "tablet" and s.components_mg == (Decimal(500),)


@pytest.mark.parametrize("raw", ["", "amoxicillin", "250 mg", ".5 mg/5 mL", "0 mg/5 mL", "250 mg/0 mL", "1,000 mg/5 mL"])
def test_strength_rejects(raw):
    with pytest.raises(Unparseable):
        parse_strength(raw)


def test_equivalent_strength_units_have_same_concentration():
    assert parse_strength("0.25 g/5 mL").same_concentration(parse_strength("250 mg/5 mL"))
    assert parse_strength("50 mg/mL").same_concentration(parse_strength("250 mg/5 mL"))
    assert not parse_strength("400/57 mg/5 mL").same_concentration(parse_strength("250/62.5 mg/5 mL"))


@pytest.mark.parametrize("raw,ml", [("5 mL", "5"), ("5 ml", "5"), ("5cc", "5"), ("2,5 mL", "2.5"), ("7.5 mL (300 mg)", "7.5")])
def test_dose_volume(raw, ml):
    assert str(parse_dose(raw).volume_ml) == ml


@pytest.mark.parametrize("raw", ["1 spoon", "one teaspoon", "2.5 or 7.5 mL", "2.5-5 mL", "1 cap", "5 mL?", "5 mL 10 mL"])
def test_dose_fails_closed(raw):
    with pytest.raises(Unparseable):
        parse_dose(raw)


@pytest.mark.parametrize("raw,n", [
    ("BID", 2), ("b.i.d.", 2), ("twice daily", 2), ("twice a day", 2), ("every 12 hours", 2), ("q12h", 2),
    ("TID", 3), ("q8h", 3), ("three times a day", 3), ("QID", 4), ("q6h", 4), ("once daily", 1), ("daily", 1),
    ("2 fois par jour", 2), ("deux fois par jour", 2), ("every 24 hours", 1),
    ("three times daily", 3), ("four times daily", 4), ("3 times a day", 3), ("3x/day", 3), ("once a day", 1),
    ("une fois par jour", 1), ("3 fois par jour", 3), ("twice a day for 5 days", 2),
])
def test_frequency(raw, n):
    assert parse_frequency(raw).per_day == n


@pytest.mark.parametrize("raw", ["prn", "as needed", "q6-8h", "every 6 to 8 hours", "q5h", "sometimes", "twice daily, TID"])
def test_frequency_fails_closed(raw):
    with pytest.raises(Unparseable):
        parse_frequency(raw)


@pytest.mark.parametrize("raw,d", [("5 days", 5), ("for 10 days", 10), ("x 7 days", 7), ("5/7", 5), ("1 week", 7), ("10 jours", 10)])
def test_duration(raw, d):
    assert parse_duration_days(raw) == d


def test_weight():
    assert parse_weight_kg("12,5 kg") == Decimal("12.5")
    assert parse_weight_kg("Weight: 14 kg") == Decimal(14)
    assert parse_weight_kg("30 lb") == Decimal("13.61")
    with pytest.raises(Unparseable):
        parse_weight_kg("14")


def test_age():
    assert parse_age_months("2 years") == Decimal(24)
    assert parse_age_months("14 months") == Decimal(14)
    assert parse_age_months("2 ans 3 mois") == Decimal(27)
    with pytest.raises(Unparseable):
        parse_age_months("2")


@pytest.mark.parametrize("raw,d", [
    ("EXP 03/2027", date(2027, 3, 31)), ("EXP 2027-03", date(2027, 3, 31)), ("2027-03-15", date(2027, 3, 15)),
    ("MAR 2027", date(2027, 3, 31)), ("Exp: 02/28", date(2028, 2, 29)),
])
def test_expiry(raw, d):
    assert parse_expiry(raw) == d


def test_lot_and_volume():
    assert parse_lot("LOT k4471") == "K4471"
    assert parse_volume_ml("100 mL after reconstitution") == Decimal(100)
    with pytest.raises(Unparseable):
        parse_volume_ml("75 mL or 100 mL")


@given(st.decimals(min_value=Decimal("0.5"), max_value=Decimal("40"), places=1))
def test_weight_roundtrip(w):
    assert parse_weight_kg(f"{w} kg") == w.normalize()


@given(st.integers(min_value=1, max_value=2000), st.sampled_from([1, 5, 10]))
def test_strength_scaling_invariance(mg, vol):
    """Scaling amount and reference volume together never changes the concentration."""
    a = parse_strength(f"{mg} mg/{vol} mL")
    b = parse_strength(f"{mg * 2} mg/{vol * 2} mL")
    assert a.same_concentration(b)


@given(st.decimals(min_value=Decimal("0.1"), max_value=Decimal("30"), places=1))
def test_dose_decimal_comma_equivalence(v):
    dot = parse_dose(f"{v} mL").volume_ml
    comma = parse_dose(f"{str(v).replace('.', ',')} mL").volume_ml
    assert dot == comma
