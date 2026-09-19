"""RxLint deterministic clinical kernel.

``verify(snapshot, pack)`` evaluates every rule in the pack against the snapshot and returns a
:class:`Verification`. There is no model call, clock read or network access in this module; the
same snapshot and pack always produce the same result hash.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Callable

from pydantic import BaseModel, Field

from .evidence import Evidence, EvidenceKind
from .normalize import Normalizer
from .rulepack import SEVERITY_RANK, Rule, RulePack
from .snapshot import MANDATORY, OPTIONAL, Snapshot
from .units import Calc, fmt

ENGINE_VERSION = "rxlint-core-0.1.0"

PASS, FAIL, CANNOT, NA, OOS = "pass", "fail", "cannot_evaluate", "not_applicable", "out_of_scope"

FACT_LABEL = {
    "rx.product": "the prescribed medicine", "rx.strength": "the prescribed strength", "rx.dose": "the dose",
    "rx.frequency": "the frequency", "rx.duration_days": "the duration", "rx.indication": "the indication",
    "rx.route": "the route", "rx.dosage_form": "the prescribed form", "dispensed.product": "the medicine on the label",
    "dispensed.strength": "the label strength", "dispensed.expiry": "the expiry date", "dispensed.volume_ml": "the pack volume",
    "dispensed.dosage_form": "the label form", "patient.weight_kg": "the weight", "patient.age_months": "the age",
    "patient.allergies": "the allergy history", "patient.current_medications": "the current medicines",
}


def _label(key: str) -> str:
    return FACT_LABEL.get(key, key)


def _reason(key: str, reason: str | None) -> str:
    r = reason or ""
    r = r.split("; ")[0]
    if "P-PERC-02" in r:
        return f"{_label(key)} reading was not corroborated by an independent reader (P-PERC-02)"
    if "competing readings" in r:
        return f"{_label(key)} has competing readings ({r.split(': ', 1)[-1]})"
    if "disagree" in r:
        return f"sources disagree on {_label(key)} ({r.split(': ', 1)[-1]})"
    return f"{_label(key)}: {r.split(': ', 1)[-1]}" if r else _label(key)


ACTION_FOR_FACT = {
    "patient.weight_kg": "REQUEST_WEIGHT",
    "patient.age_months": "REQUEST_AGE",
    "patient.allergies": "REQUEST_ALLERGY_CONFIRMATION",
    "patient.current_medications": "REQUEST_MEDICATION_LIST",
    "rx.indication": "REQUEST_INDICATION",
}


class Finding(BaseModel):
    finding_id: str
    rule_id: str
    rule_version: str
    title: str
    type: str
    status: str
    severity: str | None = None
    message: str
    facts: dict[str, Any] = Field(default_factory=dict)
    evidence: list[str] = Field(default_factory=list)
    calculations: list[dict[str, Any]] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)
    action: str = "none"
    source: dict[str, Any] = Field(default_factory=dict)
    policies: list[str] = Field(default_factory=list)


class Verification(BaseModel):
    state: str
    summary: dict[str, int]
    findings: list[Finding]
    coverage: dict[str, Any]
    clarification: dict[str, Any] | None
    snapshot_sha256: str
    rulepack: dict[str, Any]
    engine: str
    result_sha256: str
    evidence: dict[str, Any]


class _Ctx:
    def __init__(self, snap: Snapshot, pack: RulePack):
        self.snap = snap
        self.pack = pack
        self.n = Normalizer(pack)
        self.calc_count = 0
        self.tol = Decimal(str(pack.policies["P-ROUND-01"]["value"]))
        self.escalate = Decimal(str(pack.policies["P-SEV-01"]["value"]))

    def f(self, key: str):
        return self.snap.fact(key)

    def val(self, key: str) -> Any:
        return self.snap.fact(key).value

    def ok(self, key: str) -> bool:
        return self.snap.fact(key).status == "present"

    def ev(self, *keys: str) -> list[str]:
        return [self.snap.fact(k).evidence for k in keys if self.snap.fact(k).evidence]

    def add_calc(self, calc: Calc, parents: list[str]) -> str:
        self.calc_count += 1
        ev_id = f"ev_calc_{self.calc_count:03d}"
        if ev_id not in self.snap.graph.nodes:
            self.snap.graph.add(
                Evidence(
                    id=ev_id,
                    kind=EvidenceKind.DERIVED_CALCULATION,
                    name=calc.name,
                    value=fmt(calc.value, 3),
                    unit=calc.unit,
                    status="derived",
                    formula=calc.formula,
                    method=ENGINE_VERSION,
                    parents=[p for p in parents if p],
                    notes=calc.steps,
                )
            )
        return ev_id

    @property
    def product(self) -> str | None:
        """The product the patient will actually receive."""
        if self.ok("dispensed.product"):
            return self.val("dispensed.product")
        return None


def _D(s: Any) -> Decimal:
    return Decimal(str(s))


# ---------------------------------------------------------------------------- dose helpers
def component_dose(ctx: _Ctx, component: str) -> tuple[Decimal, Calc, list[str]] | None:
    """mg of ``component`` in one administered dose of the dispensed product."""
    dose = ctx.val("rx.dose")
    product = ctx.product
    if dose is None or product is None:
        return None
    comps = ctx.n.components(product)
    idx = comps.index(component)
    strength = ctx.val("dispensed.strength")
    if dose.get("volume_ml") and strength and strength.get("per_ml"):
        vol = _D(dose["volume_ml"])
        amount = _D(strength["components_mg"][idx])
        per = _D(strength["per_ml"])
        mg = vol * amount / per
        calc = Calc(
            name=f"{component}_mg_per_dose",
            formula="dose_volume_ml x component_mg / reference_volume_ml",
            inputs={"dose_volume_ml": fmt(vol, 3), "component_mg": fmt(amount, 3), "reference_volume_ml": fmt(per, 3)},
            value=mg,
            unit="mg/dose",
            steps=[f"{fmt(vol, 3)} mL x {fmt(amount, 3)} mg / {fmt(per, 3)} mL = {fmt(mg, 3)} mg"],
        )
        return mg, calc, ctx.ev("rx.dose", "dispensed.strength")
    if dose.get("units") and strength and strength.get("per_unit"):
        units = _D(dose["units"])
        amount = _D(strength["components_mg"][idx])
        mg = units * amount
        calc = Calc(
            name=f"{component}_mg_per_dose",
            formula="units x component_mg_per_unit",
            inputs={"units": fmt(units, 3), "component_mg_per_unit": fmt(amount, 3)},
            value=mg,
            unit="mg/dose",
            steps=[f"{fmt(units, 3)} x {fmt(amount, 3)} mg = {fmt(mg, 3)} mg"],
        )
        return mg, calc, ctx.ev("rx.dose", "dispensed.strength")
    if dose.get("mass_mg") and idx == 0 and not dose.get("volume_ml"):
        mg = _D(dose["mass_mg"])
        calc = Calc(name=f"{component}_mg_per_dose", formula="prescribed mass", inputs={"mass_mg": fmt(mg, 3)},
                    value=mg, unit="mg/dose", steps=[f"prescribed {fmt(mg, 3)} mg per dose"])
        return mg, calc, ctx.ev("rx.dose")
    return None


def within(value: Decimal, lo: Decimal, hi: Decimal, tol: Decimal) -> bool:
    return lo * (1 - tol) <= value <= hi * (1 + tol)


# ---------------------------------------------------------------------------- evaluators
Result = tuple[str, str, dict[str, Any]]  # status, message, extra


def ev_scope_ingredient(rule: Rule, ctx: _Ctx) -> Result:
    in_scope = set(ctx.pack.scope["ingredients"])
    f = ctx.f("rx.product")
    if f.status == "present":
        if f.value in in_scope:
            return PASS, f"{ctx.n.display(f.value)} is covered by this pack.", {"evidence": ctx.ev("rx.product")}
        return OOS, f"{f.value} is outside this pack.", {"evidence": ctx.ev("rx.product")}
    if f.status == "unrecognised":
        return OOS, f"'{f.raw}' is not one of the pack's products.", {"evidence": ctx.ev("rx.product")}
    if f.status == "ambiguous":
        return CANNOT, f"The prescribed medicine could not be identified: {f.reason}.", {
            "missing": ["rx.product"], "action": "REQUEST_FIELD_CONFIRMATION", "evidence": ctx.ev("rx.product")}
    return CANNOT, "The prescribed medicine is missing.", {"missing": ["rx.product"], "action": "REQUEST_NEW_PHOTO"}


def ev_scope_route(rule: Rule, ctx: _Ctx) -> Result:
    f = ctx.f("rx.route")
    if f.status != "present":
        return CANNOT, "The route of administration is not stated.", {"missing": ["rx.route"]}
    if f.value in rule.params["allowed"]:
        return PASS, "Route is oral.", {"evidence": ctx.ev("rx.route")}
    return OOS, f"Route '{f.value}' is outside this pack (oral only).", {"evidence": ctx.ev("rx.route")}


def ev_scope_age(rule: Rule, ctx: _Ctx) -> Result:
    age = _D(ctx.val("patient.age_months"))
    lo, hi = _D(rule.params["min_months"]), _D(rule.params["max_months_exclusive"])
    facts = {"age_months": fmt(age, 1)}
    if lo <= age < hi:
        return PASS, f"Age {fmt(age, 1)} months is within 28 days to 12 years.", {"facts": facts, "evidence": ctx.ev("patient.age_months")}
    return OOS, f"Age {fmt(age, 1)} months is outside 28 days to 12 years.", {"facts": facts, "evidence": ctx.ev("patient.age_months")}


def ev_scope_weight(rule: Rule, ctx: _Ctx) -> Result:
    w = _D(ctx.val("patient.weight_kg"))
    if w >= _D(rule.params["min_kg"]):
        return PASS, f"Weight {fmt(w, 2)} kg is within the WHO weight bands.", {"evidence": ctx.ev("patient.weight_kg")}
    return OOS, f"Weight {fmt(w, 2)} kg is below the smallest WHO weight band (3 kg).", {"evidence": ctx.ev("patient.weight_kg")}


def ev_identity(rule: Rule, ctx: _Ctx) -> Result:
    a, b = ctx.val("rx.product"), ctx.val("dispensed.product")
    if ctx.f("dispensed.product").status == "unrecognised":
        raw = ctx.f("dispensed.product").raw
        return FAIL, f"Prescribed {ctx.n.display(a)} but the medicine reads '{raw}'.", {
            "facts": {"prescribed": ctx.n.display(a), "dispensed": raw},
            "evidence": ctx.ev("rx.product", "dispensed.product"), "action": "professional_review_required"}
    facts = {"prescribed": ctx.n.display(a), "dispensed": ctx.n.display(b)}
    if a == b:
        return PASS, f"Both are {ctx.n.display(a)}.", {"facts": facts, "evidence": ctx.ev("rx.product", "dispensed.product")}
    return FAIL, f"Prescribed {ctx.n.display(a)} but the medicine is {ctx.n.display(b)}.", {
        "facts": facts, "evidence": ctx.ev("rx.product", "dispensed.product"), "action": "professional_review_required"}


def ev_form(rule: Rule, ctx: _Ctx) -> Result:
    a, b = ctx.val("rx.dosage_form"), ctx.val("dispensed.dosage_form")
    facts = {"prescribed_form": a, "dispensed_form": b}
    if a == b:
        return PASS, f"Both are {a.replace('_', ' ')}.", {"facts": facts, "evidence": ctx.ev("rx.dosage_form", "dispensed.dosage_form")}
    return FAIL, f"Prescribed as {a.replace('_', ' ')} but dispensed as {b.replace('_', ' ')}.", {
        "facts": facts, "evidence": ctx.ev("rx.dosage_form", "dispensed.dosage_form"), "action": "professional_review_required"}


def _strength_text(s: dict[str, Any]) -> str:
    comps = " / ".join(f"{c} mg" for c in s["components_mg"])
    if s.get("per_ml"):
        return f"{comps} per {s['per_ml']} mL"
    return f"{comps} per {s.get('per_unit') or 'unit'}"


def ev_concentration(rule: Rule, ctx: _Ctx) -> Result:
    if not ctx.ok("rx.strength"):
        return NA, "The prescription does not state a concentration; RX-PRODUCT-004 applies.", {}
    a, b = ctx.val("rx.strength"), ctx.val("dispensed.strength")
    facts = {"prescribed_strength": _strength_text(a), "dispensed_strength": _strength_text(b)}
    same = len(a["components_mg"]) == len(b["components_mg"]) and bool(a.get("per_ml")) == bool(b.get("per_ml"))
    calcs: list[tuple[Calc, list[str]]] = []
    if same and a.get("per_ml"):
        for i, (ca, cb) in enumerate(zip(a["components_mg"], b["components_mg"])):
            ra, rb = _D(ca) / _D(a["per_ml"]), _D(cb) / _D(b["per_ml"])
            calcs.append((Calc(
                name=f"component_{i + 1}_mg_per_ml",
                formula="component_mg / reference_volume_ml, prescription vs dispensed",
                inputs={"prescribed": f"{ca} mg / {a['per_ml']} mL", "dispensed": f"{cb} mg / {b['per_ml']} mL"},
                value=rb - ra, unit="mg/mL difference",
                steps=[f"prescribed {ca}/{a['per_ml']} = {fmt(ra, 3)} mg/mL", f"dispensed {cb}/{b['per_ml']} = {fmt(rb, 3)} mg/mL"],
            ), ctx.ev("rx.strength", "dispensed.strength")))
            same = same and ra == rb
    elif same:
        same = a["components_mg"] == b["components_mg"] and a.get("per_unit") == b.get("per_unit")
    extra = {"facts": facts, "evidence": ctx.ev("rx.strength", "dispensed.strength"), "calcs": calcs}
    if same:
        return PASS, f"Concentration matches: {facts['dispensed_strength']}.", extra
    extra["action"] = "professional_review_required"
    return FAIL, (f"Prescribed {facts['prescribed_strength']} but the medicine is {facts['dispensed_strength']}. "
                  "The same volume delivers a different dose."), extra


def ev_volume_needs_strength(rule: Rule, ctx: _Ctx) -> Result:
    dose = ctx.val("rx.dose")
    if not dose.get("volume_ml"):
        return NA, "The dose is written as an amount, not a volume.", {}
    if ctx.ok("rx.strength"):
        return PASS, "The prescription states the concentration its volume dose refers to.", {"evidence": ctx.ev("rx.strength", "rx.dose")}
    if ctx.f("rx.strength").status == "ambiguous":
        return CANNOT, f"The prescribed concentration is unreadable: {ctx.f('rx.strength').reason}.", {
            "missing": ["rx.strength"], "action": "REQUEST_NEW_PHOTO", "evidence": ctx.ev("rx.strength")}
    return CANNOT, (f"The prescription gives {dose['volume_ml']} mL without a concentration, so the intended dose "
                    "cannot be recovered."), {"missing": ["rx.strength"], "action": "REQUEST_FIELD_CONFIRMATION"}


def ev_expiry(rule: Rule, ctx: _Ctx) -> Result:
    exp = date.fromisoformat(ctx.val("dispensed.expiry"))
    today = date.fromisoformat(ctx.val("context.dispense_date"))
    facts = {"expiry": exp.isoformat(), "dispense_date": today.isoformat()}
    ev = ctx.ev("dispensed.expiry", "context.dispense_date")
    if exp < today:
        return FAIL, f"The medicine expired on {exp.isoformat()}.", {"facts": facts, "evidence": ev, "action": "professional_review_required"}
    if ctx.ok("rx.duration_days"):
        days = int(_D(ctx.val("rx.duration_days")))
        end = today + timedelta(days=max(days - 1, 0))
        facts["course_end"] = end.isoformat()
        if exp < end:
            return FAIL, f"The medicine expires on {exp.isoformat()}, before the course ends on {end.isoformat()}.", {
                "facts": facts, "evidence": ev + ctx.ev("rx.duration_days"), "severity": rule.params["course_end_severity"],
                "action": "professional_review_required"}
    return PASS, f"In date until {exp.isoformat()}.", {"facts": facts, "evidence": ev}


def ev_quantity(rule: Rule, ctx: _Ctx) -> Result:
    dose = ctx.val("rx.dose")
    if not dose.get("volume_ml"):
        return NA, "Quantity check applies to volume doses.", {}
    if not ctx.ok("dispensed.volume_ml"):
        return NA, "The supplied volume is not printed on the product.", {}
    vol, per_day, days = _D(dose["volume_ml"]), _D(ctx.val("rx.frequency")["per_day"]), _D(ctx.val("rx.duration_days"))
    need = vol * per_day * days
    have = _D(ctx.val("dispensed.volume_ml"))
    calc = Calc(name="course_volume_ml", formula="dose_volume_ml x doses_per_day x days",
                inputs={"dose_volume_ml": fmt(vol, 3), "doses_per_day": fmt(per_day, 0), "days": fmt(days, 0)},
                value=need, unit="mL", steps=[f"{fmt(vol, 3)} x {fmt(per_day, 0)} x {fmt(days, 0)} = {fmt(need, 2)} mL",
                                               f"supplied {fmt(have, 2)} mL"])
    facts = {"needed_ml": fmt(need, 2), "supplied_ml": fmt(have, 2)}
    extra = {"facts": facts, "calcs": [(calc, ctx.ev("rx.dose", "rx.frequency", "rx.duration_days", "dispensed.volume_ml"))],
             "evidence": ctx.ev("dispensed.volume_ml")}
    if need <= have:
        return PASS, f"The course needs {fmt(need, 2)} mL; {fmt(have, 2)} mL is supplied.", extra
    extra["action"] = "professional_review_required"
    return FAIL, f"The course needs {fmt(need, 2)} mL but only {fmt(have, 2)} mL is supplied.", extra


def ev_weight_dose(rule: Rule, ctx: _Ctx) -> Result:
    comp = rule.component
    got = component_dose(ctx, comp)
    if got is None:
        return CANNOT, "The dose per administration could not be computed.", {"missing": ["rx.dose"]}
    mg_dose, calc_dose, dose_parents = got
    per_day = _D(ctx.val("rx.frequency")["per_day"])
    w = _D(ctx.val("patient.weight_kg"))
    p = rule.params
    tol = ctx.tol
    calc_parents = dose_parents
    calcs: list[tuple[Calc, list[str]]] = [(calc_dose, calc_parents)]
    mg_day = mg_dose * per_day
    if p["basis"] == "per_day":
        value = mg_day / w
        calcs.append((Calc(name=f"{comp}_mg_per_kg_day", formula="mg_per_dose x doses_per_day / weight_kg",
                           inputs={"mg_per_dose": fmt(mg_dose, 3), "doses_per_day": fmt(per_day, 0), "weight_kg": fmt(w, 2)},
                           value=value, unit="mg/kg/day",
                           steps=[f"{fmt(mg_dose, 3)} mg x {fmt(per_day, 0)} / {fmt(w, 2)} kg = {fmt(value, 2)} mg/kg/day"]),
                      calc_parents + ctx.ev("rx.frequency", "patient.weight_kg")))
        unit = "mg/kg/day"
    else:
        value = mg_dose / w
        calcs.append((Calc(name=f"{comp}_mg_per_kg_dose", formula="mg_per_dose / weight_kg",
                           inputs={"mg_per_dose": fmt(mg_dose, 3), "weight_kg": fmt(w, 2)},
                           value=value, unit="mg/kg/dose",
                           steps=[f"{fmt(mg_dose, 3)} mg / {fmt(w, 2)} kg = {fmt(value, 2)} mg/kg/dose"]),
                      calc_parents + ctx.ev("patient.weight_kg")))
        unit = "mg/kg/dose"

    facts: dict[str, Any] = {"component": comp, "mg_per_dose": fmt(mg_dose, 2), "mg_per_day": fmt(mg_day, 2),
                             "weight_kg": fmt(w, 2), "value": fmt(value, 2), "unit": unit, "tolerance_pct": fmt(tol * 100, 0)}

    # Weight-band route
    band_hit = None
    for band in p.get("weight_bands", []):
        lo, hi = _D(band["min"]), _D(band["max"]) if "max" in band else None
        if w >= lo and (hi is None or w < hi):
            bd = _D(band["dose_mg"])
            if abs(mg_dose - bd) <= bd * tol and per_day == _D(band["per_day"]):
                band_hit = band
                break
    below = p.get("mg_per_kg_below_kg")
    mgkg_applies = below is None or w < _D(below)

    if "options_mg_per_kg" in p:
        options = [_D(o) for o in p["options_mg_per_kg"]]
        lo, hi = min(options), max(options)
        in_range = any(within(value, o, o, tol) for o in options)
        facts["range"] = " or ".join(fmt(o, 2) for o in options) + f" {unit}"
    else:
        lo, hi = (_D(x) for x in p["range_mg_per_kg"])
        in_range = within(value, lo, hi, tol)
        facts["range"] = (f"{fmt(lo, 2)}–{fmt(hi, 2)}" if lo != hi else fmt(lo, 2)) + f" {unit}"
    facts["accepted"] = f"{fmt(lo * (1 - tol), 2)}–{fmt(hi * (1 + tol), 2)} {unit}"
    extra: dict[str, Any] = {"facts": facts, "calcs": calcs, "evidence": ctx.ev("patient.weight_kg", "rx.dose", "rx.frequency", "dispensed.strength"),
                             "policies": ["P-ROUND-01"]}
    if band_hit is not None:
        band_txt = f"{band_hit['dose_mg']} mg {band_hit['per_day']}x/day for {band_hit['min']}" + (f"–<{band_hit['max']} kg" if "max" in band_hit else "+ kg")
        facts["band"] = band_txt
        return PASS, f"{fmt(mg_dose, 2)} mg {fmt(per_day, 0)}x/day matches the WHO weight band ({band_txt}).", extra
    if mgkg_applies and in_range:
        return PASS, f"{fmt(value, 2)} {unit} is within {facts['range']} (±{facts['tolerance_pct']}% measuring tolerance).", extra
    if not mgkg_applies:
        adult = [b for b in p.get("weight_bands", []) if b.get("adult")]
        facts["range"] = " or ".join(f"{b['dose_mg']} mg {b['per_day']}x/day" for b in adult) + " (adult dose)"
        ratio = mg_day / (_D(adult[0]["dose_mg"]) * _D(adult[0]["per_day"])) if adult else Decimal(1)
        sev = "critical" if ratio >= ctx.escalate or ratio <= 1 / ctx.escalate else rule.severity
        extra.update(severity=sev, action="professional_review_required")
        extra["policies"].append("P-SEV-01")
        return FAIL, f"At {fmt(w, 2)} kg WHO directs the adult dose ({facts['range']}); prescribed {fmt(mg_dose, 2)} mg {fmt(per_day, 0)}x/day.", extra
    high = value > hi * (1 + tol)
    ratio = value / hi if high else value / lo
    facts["direction"] = "above" if high else "below"
    facts["ratio"] = fmt(ratio, 2)
    sev = "critical" if (high and ratio >= ctx.escalate) or (not high and ratio <= 1 / ctx.escalate) else rule.severity
    extra.update(severity=sev, action="professional_review_required")
    extra["policies"].append("P-SEV-01")
    return FAIL, (f"{fmt(value, 2)} {unit} is {facts['direction']} the WHO range {facts['range']} "
                  f"({fmt(ratio * 100, 0)}% of the {'upper' if high else 'lower'} bound)."), extra


def ev_max_daily(rule: Rule, ctx: _Ctx) -> Result:
    got = component_dose(ctx, rule.component)
    if got is None:
        return CANNOT, "The daily amount could not be computed.", {"missing": ["rx.dose"]}
    mg_dose, calc_dose, parents = got
    per_day = _D(ctx.val("rx.frequency")["per_day"])
    daily = mg_dose * per_day
    limit = _D(rule.params["limit_mg"])
    calc = Calc(name=f"{rule.component}_mg_per_day", formula="mg_per_dose x doses_per_day",
                inputs={"mg_per_dose": fmt(mg_dose, 3), "doses_per_day": fmt(per_day, 0)}, value=daily, unit="mg/day",
                steps=[f"{fmt(mg_dose, 3)} mg x {fmt(per_day, 0)} = {fmt(daily, 2)} mg/day", f"limit {fmt(limit, 0)} mg/day"])
    facts = {"mg_per_day": fmt(daily, 2), "limit_mg": fmt(limit, 0), "component": rule.component}
    extra = {"facts": facts, "calcs": [(calc_dose, parents), (calc, parents + ctx.ev("rx.frequency"))]}
    if daily <= limit:
        return PASS, f"{fmt(daily, 2)} mg/day is within the {fmt(limit, 0)} mg maximum.", extra
    extra["action"] = "professional_review_required" if rule.severity != "advisory" else "none"
    return FAIL, f"{fmt(daily, 2)} mg/day exceeds the {fmt(limit, 0)} mg daily maximum.", extra


def ev_frequency(rule: Rule, ctx: _Ctx) -> Result:
    per_day = int(_D(ctx.val("rx.frequency")["per_day"]))
    allowed = rule.params.get("per_day")
    if allowed is None:
        w = _D(ctx.val("patient.weight_kg"))
        for b in rule.params["by_weight"]:
            if w >= _D(b["min"]) and ("max" not in b or w < _D(b["max"])):
                allowed = b["per_day"]
                break
    allowed = allowed or []
    facts = {"per_day": per_day, "allowed": allowed}
    labels = {1: "once daily", 2: "every 12 hours", 3: "every 8 hours", 4: "every 6 hours"}
    ev = ctx.ev("rx.frequency", "patient.weight_kg")
    if per_day in allowed:
        return PASS, f"{labels.get(per_day, f'{per_day}x/day')} is a WHO interval for this medicine.", {"facts": facts, "evidence": ev}
    want = " or ".join(labels.get(a, f"{a}x/day") for a in allowed)
    return FAIL, f"Prescribed {labels.get(per_day, f'{per_day}x/day')}; WHO gives {want}.", {
        "facts": facts, "evidence": ev, "action": "professional_review_required"}


def ev_duration(rule: Rule, ctx: _Ctx) -> Result:
    if ctx.val("rx.indication") != rule.indication:
        return NA, "Stated indication differs.", {}
    product = ctx.product
    spec = rule.params["by_product"].get(product)
    if spec is None:
        return NA, "This product is not listed for the indication; see AWARE-IND-001.", {}
    days = _D(ctx.val("rx.duration_days"))
    if "days" in spec:
        ok = days in [_D(d) for d in spec["days"]]
        want = " or ".join(str(d) for d in spec["days"]) + " days"
    else:
        lo, hi = (_D(x) for x in spec["days_range"])
        ok = lo <= days <= hi
        want = f"{fmt(lo, 0)}–{fmt(hi, 0)} days"
    facts = {"days": fmt(days, 0), "expected": want, "indication": ctx.pack.indications[rule.indication]["display"]}
    ev = ctx.ev("rx.duration_days", "rx.indication")
    if ok:
        return PASS, f"{fmt(days, 0)} days matches WHO ({want}) for {facts['indication'].lower()}.", {"facts": facts, "evidence": ev}
    return FAIL, f"{fmt(days, 0)} days; WHO gives {want} for {facts['indication'].lower()}.", {
        "facts": facts, "evidence": ev, "action": "professional_review_required"}


def ev_indication_option(rule: Rule, ctx: _Ctx) -> Result:
    ind = ctx.val("rx.indication")
    product = ctx.val("rx.product")
    options = {p for r in ctx.pack.rules if r.type == "duration_allowed" and r.indication == ind for p in r.params["by_product"]}
    display = ctx.pack.indications[ind]["display"]
    if product in options:
        return PASS, f"{ctx.n.display(product)} is a WHO AWaRe option for {display.lower()}.", {"evidence": ctx.ev("rx.indication", "rx.product")}
    return FAIL, (f"{ctx.n.display(product)} is not among the WHO AWaRe options for {display.lower()} "
                  f"({', '.join(ctx.n.display(o) for o in sorted(options))})."), {"evidence": ctx.ev("rx.indication", "rx.product")}


def ev_allergy_recognised(rule: Rule, ctx: _Ctx) -> Result:
    entries = ctx.val("patient.allergies") or []
    bad = [e for e in entries if e["status"] != "exact"]
    if not entries:
        return PASS, "No known drug allergies reported.", {"evidence": ctx.ev("patient.allergies")}
    if bad:
        names = ", ".join(f"'{e['raw']}'" for e in bad)
        return CANNOT, f"Allergy {names} is not a recognised allergen term; confirm what it refers to.", {
            "facts": {"unrecognised": [e["raw"] for e in bad]}, "evidence": ctx.ev("patient.allergies"),
            "action": "REQUEST_ALLERGY_CONFIRMATION", "missing": ["patient.allergies"]}
    return PASS, "Every reported allergy is recognised.", {"evidence": ctx.ev("patient.allergies")}


def ev_allergy(rule: Rule, ctx: _Ctx) -> Result:
    entries = [e for e in (ctx.val("patient.allergies") or []) if e["status"] == "exact"]
    product = ctx.product
    pclasses = ctx.n.product_classes(product) & set(rule.params["product_classes"])
    hits = [e for e in entries if e["value"] in rule.params["allergy_classes"]]
    if not pclasses:
        return NA, "Product class not covered by this rule.", {}
    if hits:
        names = ", ".join(e["raw"] for e in hits)
        return FAIL, f"Reported allergy to {names}; {ctx.n.display(product)} is a {'/'.join(sorted(pclasses))}.", {
            "facts": {"allergy": names, "product": ctx.n.display(product), "class": "/".join(sorted(pclasses))},
            "evidence": ctx.ev("patient.allergies", "dispensed.product"), "action": "professional_review_required"}
    return PASS, "No reported allergy conflicts with this product class.", {"evidence": ctx.ev("patient.allergies")}


def ev_min_age(rule: Rule, ctx: _Ctx) -> Result:
    age = _D(ctx.val("patient.age_months"))
    lim = _D(rule.params["min_months"])
    if age >= lim:
        return PASS, f"Age {fmt(age, 1)} months is at least {fmt(lim, 0)} months.", {"evidence": ctx.ev("patient.age_months")}
    return FAIL, f"Age {fmt(age, 1)} months is below the labelled minimum of {fmt(lim, 0)} months.", {
        "facts": {"age_months": fmt(age, 1), "min_months": fmt(lim, 0)}, "evidence": ctx.ev("patient.age_months"),
        "action": "professional_review_required"}


def _meds(ctx: _Ctx) -> list[dict[str, Any]]:
    return [m for m in (ctx.val("patient.current_medications") or []) if m["status"] == "exact" and m["value"] != "none"]


def ev_duplicate_ingredient(rule: Rule, ctx: _Ctx) -> Result:
    comps = set(ctx.n.components(ctx.product))
    for m in _meds(ctx):
        overlap = comps & set(ctx.n.med_ingredients(m["value"]))
        if overlap:
            return FAIL, f"Current medicine '{m['raw']}' already contains {', '.join(sorted(overlap))}.", {
                "facts": {"medicine": m["raw"]}, "evidence": ctx.ev("patient.current_medications", "dispensed.product"),
                "action": "professional_review_required"}
    return PASS, "No current medicine repeats an active ingredient.", {"evidence": ctx.ev("patient.current_medications")}


def ev_duplicate_class(rule: Rule, ctx: _Ctx) -> Result:
    pc = ctx.n.product_classes(ctx.product) & set(rule.params["classes"])
    comps = set(ctx.n.components(ctx.product))
    for m in _meds(ctx):
        ings = ctx.n.med_ingredients(m["value"])
        if comps & set(ings):
            continue
        mc = set().union(*(ctx.n.ingredient_classes(i) for i in ings)) if ings else set()
        if m["value"] in ctx.n.products:
            mc |= ctx.n.product_classes(m["value"])
        overlap = pc & mc
        if overlap:
            return FAIL, f"Current medicine '{m['raw']}' is another {', '.join(sorted(overlap))}.", {
                "facts": {"medicine": m["raw"]}, "evidence": ctx.ev("patient.current_medications"),
                "action": "professional_review_required"}
    return PASS, "No second antibiotic of the same class.", {"evidence": ctx.ev("patient.current_medications")}


def ev_interaction(rule: Rule, ctx: _Ctx) -> Result:
    comps = set(ctx.n.components(ctx.product))
    if not comps & set(rule.params["product_ingredients"]):
        return NA, "Rule does not apply to this product.", {}
    partners = set(rule.params.get("with", []))
    partner_classes = set(rule.params.get("with_classes", []))
    for m in _meds(ctx):
        for ing in ctx.n.med_ingredients(m["value"]):
            if ing in partners or ctx.n.ingredient_classes(ing) & partner_classes:
                return FAIL, f"{ctx.n.display(ctx.product)} with current medicine '{m['raw']}'.", {
                    "facts": {"medicine": m["raw"]}, "evidence": ctx.ev("patient.current_medications", "dispensed.product"),
                    "action": "professional_review_required"}
    return PASS, "No listed partner drug among current medicines.", {"evidence": ctx.ev("patient.current_medications")}


EVALUATORS: dict[str, Callable[[Rule, _Ctx], Result]] = {
    "scope_ingredient": ev_scope_ingredient,
    "scope_route": ev_scope_route,
    "scope_age": ev_scope_age,
    "scope_weight": ev_scope_weight,
    "identity_match": ev_identity,
    "form_match": ev_form,
    "concentration_match": ev_concentration,
    "volume_needs_strength": ev_volume_needs_strength,
    "expiry": ev_expiry,
    "quantity": ev_quantity,
    "weight_dose": ev_weight_dose,
    "max_daily_dose": ev_max_daily,
    "frequency_allowed": ev_frequency,
    "duration_allowed": ev_duration,
    "indication_option": ev_indication_option,
    "allergy_recognised": ev_allergy_recognised,
    "allergy_contraindication": ev_allergy,
    "min_age": ev_min_age,
    "duplicate_ingredient": ev_duplicate_ingredient,
    "duplicate_class": ev_duplicate_class,
    "interaction": ev_interaction,
}

# Rules whose missing prerequisite is optional are skipped instead of blocking PASS.
OPTIONAL_REQUIREMENTS = OPTIONAL


PRODUCT_DEPENDENT = {"allergy_contraindication", "duplicate_ingredient", "duplicate_class", "interaction", "min_age",
                     "weight_dose", "max_daily_dose", "frequency_allowed", "duration_allowed", "indication_option"}


def _relevant(rule: Rule, ctx: _Ctx) -> bool:
    """Whether a rule concerns this case at all. Irrelevant rules are omitted from the report."""
    product = ctx.product
    if rule.type in PRODUCT_DEPENDENT and product is None:
        return False  # the missing product is reported once, by RX-PRODUCT-001 / the mandatory-fact check
    if rule.type == "interaction":
        return bool(set(ctx.n.components(product)) & set(rule.params["product_ingredients"]))
    if rule.type == "allergy_contraindication":
        return bool(ctx.n.product_classes(product) & set(rule.params["product_classes"]))
    if rule.type in ("duration_allowed", "indication_option"):
        if not ctx.ok("rx.indication"):
            return False
        if rule.type == "duration_allowed" and ctx.val("rx.indication") != rule.indication:
            return False
    prod = rule.applies_to.get("product")
    if prod is not None and prod not in (product, ctx.val("rx.product")):
        return False
    return True


def _source_view(rule: Rule, pack: RulePack) -> dict[str, Any]:
    def one(src) -> dict[str, Any]:
        meta = pack.sources.get(src.ref, {}) if src.ref != "PACK" else {"title": f"RxLint pack {pack.id} {pack.version}"}
        return {"ref": src.ref, "title": meta.get("title"), "edition": meta.get("edition"), "url": meta.get("url"),
                "license": meta.get("license"), "locator": src.locator, "quotes": src.quotes}

    return {"primary": one(rule.source), "related": [one(s) for s in rule.related_sources], "explain": rule.explain}


CLINICAL_TYPES = {"weight_dose", "max_daily_dose", "frequency_allowed", "duration_allowed", "indication_option"}


def verify(snap: Snapshot, pack: RulePack) -> Verification:
    snap = snap.model_copy(deep=True)
    ctx = _Ctx(snap, pack)
    scope_blocked: list[str] = []
    findings: list[Finding] = []
    upstream_block: set[str] = set()

    # Product identity gates the product-specific dose rules: without it we do not know which table applies.
    identity_ok = ctx.ok("rx.product") and ctx.ok("dispensed.product") and ctx.val("rx.product") == ctx.val("dispensed.product")

    for i, rule in enumerate(pack.rules):
        fid = f"fd_{i + 1:03d}"
        base = dict(finding_id=fid, rule_id=rule.id, rule_version=rule.version, title=rule.title, type=rule.type,
                    source=_source_view(rule, pack))
        if not _relevant(rule, ctx):
            continue
        if rule.type in CLINICAL_TYPES and not identity_ok:
            findings.append(Finding(**base, status=NA, message="Not evaluated: the dispensed product does not match the prescription (RX-PRODUCT-001)."))
            continue
        if rule.type in CLINICAL_TYPES and scope_blocked:
            findings.append(Finding(**base, status=NA, message=f"Not evaluated: case outside pack scope ({', '.join(scope_blocked)})."))
            continue
        # requirements
        missing, ambiguous, optional_missing = [], [], []
        pre_checked = rule.type == "scope_ingredient" or (
            rule.type == "identity_match" and snap.fact("dispensed.product").status == "unrecognised" and ctx.ok("rx.product"))
        for req in ([] if pre_checked else rule.requires):
            f = snap.fact(req)
            if f.status == "present":
                continue
            if req in OPTIONAL_REQUIREMENTS or f.status == "unrecognised":
                optional_missing.append(req)
            elif f.status == "ambiguous":
                ambiguous.append(req)
            else:
                missing.append(req)
        missing, ambiguous = list(dict.fromkeys(missing)), list(dict.fromkeys(ambiguous))
        if optional_missing and not (missing or ambiguous):
            if rule.type in ("duration_allowed", "indication_option"):
                continue  # indication not supplied: these rules are silent by design
            findings.append(Finding(**base, status=NA, message=f"Skipped: {', '.join(optional_missing)} not supplied.",
                                    missing=optional_missing))
            continue
        if missing or ambiguous:
            if rule.type.startswith("scope_") and not ambiguous and rule.type != "scope_ingredient":
                # scope checks on missing patient facts surface through the dose rules' own requirements
                pass
            reasons = [_reason(k, snap.fact(k).reason) for k in ambiguous]
            confirm_only = ambiguous and all("P-PERC-02" in (snap.fact(k).reason or "") for k in ambiguous)
            action = "REQUEST_FIELD_CONFIRMATION" if confirm_only else "REQUEST_NEW_PHOTO" if any(k.startswith(("rx.", "dispensed.")) for k in ambiguous) else next(
                (ACTION_FOR_FACT[k] for k in missing + ambiguous if k in ACTION_FOR_FACT), "REQUEST_FIELD_CONFIRMATION")
            parts = []
            if missing:
                parts.append(", ".join(_label(k) for k in missing) + (" is" if len(missing) == 1 else " are") + " missing")
            parts.extend(reasons)
            msg = "Cannot evaluate: " + "; ".join(parts) + "."

            findings.append(Finding(**base, status=CANNOT, severity="cannot_verify", message=msg, missing=missing + ambiguous,
                                    action=action, evidence=[snap.fact(k).evidence for k in ambiguous if snap.fact(k).evidence]))
            continue
        status, message, extra = EVALUATORS[rule.type](rule, ctx)
        if status == OOS:
            scope_blocked.append(rule.id)
        calc_ids = []
        calc_dicts = []
        for calc, parents in extra.get("calcs", []):
            cid = ctx.add_calc(calc, parents)
            calc_ids.append(cid)
            d = calc.as_dict()
            d["evidence_id"] = cid
            calc_dicts.append(d)
        severity = None
        if status == FAIL:
            severity = extra.get("severity", rule.severity)
        elif status == OOS:
            severity = "out_of_scope"
        elif status == CANNOT:
            severity = "cannot_verify"
        action = extra.get("action", "none")
        if status == FAIL and severity == "advisory":
            action = "none"
        findings.append(Finding(**base, status=status, severity=severity, message=message, facts=extra.get("facts", {}),
                                evidence=[e for e in extra.get("evidence", []) if e] + calc_ids, calculations=calc_dicts,
                                missing=extra.get("missing", []), action=action, policies=extra.get("policies", [])))

    # Mandatory facts that no rule consumed still block PASS.
    consumed = {m for f in findings for m in f.missing}
    for key in MANDATORY:
        fact = snap.fact(key)
        if fact.status not in ("present", "unrecognised") and key not in consumed and not (scope_blocked and key.startswith("patient.")):
            findings.append(Finding(
                finding_id=f"fd_m_{key}", rule_id="RX-EVIDENCE-001", rule_version="1.0.0", title=f"Required fact {key}",
                type="mandatory_fact", status=CANNOT, severity="cannot_verify",
                message=(f"Cannot verify: {_reason(key, fact.reason)}." if fact.status == "ambiguous" else f"Cannot verify: {_label(key)} is missing."),
                missing=[key], evidence=[fact.evidence] if fact.evidence else [],
                action=("REQUEST_NEW_PHOTO" if fact.status == "ambiguous" and key.startswith(("rx.", "dispensed.")) else ACTION_FOR_FACT.get(key, "REQUEST_FIELD_CONFIRMATION")),
                source={"primary": {"ref": "PACK", "title": "RxLint evidence policy", "locator": "snapshot.MANDATORY", "quotes": []}, "related": [],
                        "explain": "PASS requires every mandatory fact to be present and unambiguous."}))

    # Overall state
    fails = [f for f in findings if f.status == FAIL and f.severity in ("critical", "high", "moderate")]
    cannots = [f for f in findings if f.status == CANNOT]
    oos = [f for f in findings if f.status == OOS]
    if fails:
        state = "REVIEW"
    elif oos:
        state = "OUT_OF_SCOPE"
    elif cannots:
        state = "CANNOT_VERIFY"
    else:
        state = "PASS"

    order = {"critical": 0, "high": 1, "moderate": 2, "cannot_verify": 3, "out_of_scope": 4, "advisory": 5, None: 6}
    status_order = {FAIL: 0, CANNOT: 1, OOS: 2, PASS: 3, NA: 4}
    findings.sort(key=lambda f: (status_order[f.status], order.get(f.severity, 6), f.rule_id))

    summary = {
        "review": len(fails),
        "cannot_verify": len(cannots),
        "out_of_scope": len(oos),
        "passed": sum(1 for f in findings if f.status == PASS),
        "notes": sum(1 for f in findings if f.status == FAIL and f.severity == "advisory"),
        "not_applicable": sum(1 for f in findings if f.status == NA),
    }

    ind = snap.fact("rx.indication")
    if ind.status == "unrecognised":
        findings.append(Finding(
            finding_id="fd_ind", rule_id="RX-EVIDENCE-003", rule_version="1.0.0", title="Indication recognised",
            type="coverage", status=FAIL, severity="advisory",
            message=f"Indication '{ind.raw}' is not one the duration rules cover; treatment duration was not checked.",
            evidence=[ind.evidence] if ind.evidence else [],
            source={"primary": {"ref": "PACK", "title": "RxLint evidence policy", "quotes": []}, "related": [], "explain": None}))
        summary["notes"] += 1

    # Interaction coverage
    covered = set()
    for r in pack.rules:
        if r.type == "interaction":
            covered |= set(r.params.get("with", []))
    covered_classes = {c for r in pack.rules if r.type == "interaction" for c in r.params.get("with_classes", [])}
    not_covered, covered_meds, unrecognised = [], [], []
    for m in (snap.fact("patient.current_medications").value or []):
        if m["status"] != "exact":
            unrecognised.append(m["raw"])
            continue
        if m["value"] == "none":
            continue
        ings = ctx.n.med_ingredients(m["value"])
        if any(i in covered or ctx.n.ingredient_classes(i) & covered_classes for i in ings) or (set(ings) & set(pack.scope["ingredients"])):
            covered_meds.append(m["raw"])
        else:
            not_covered.append(m["raw"])
    coverage = {"interaction_pairs": sum(1 for r in pack.rules if r.type == "interaction"),
                "current_medicines_covered": covered_meds, "current_medicines_not_covered": not_covered,
                "current_medicines_unrecognised": unrecognised}
    if unrecognised and state == "PASS":
        state = "CANNOT_VERIFY"
        cannots.append(Finding(finding_id="fd_cov", rule_id="RX-EVIDENCE-002", rule_version="1.0.0",
                               title="Current medicines are recognised", type="coverage", status=CANNOT, severity="cannot_verify",
                               message=f"Current medicine {', '.join(repr(u) for u in unrecognised)} is not recognised; confirm the active ingredient.",
                               action="REQUEST_MEDICATION_LIST", missing=["patient.current_medications"],
                               source={"primary": {"ref": "PACK", "title": "RxLint evidence policy", "quotes": []}, "related": [], "explain": None}))
        findings.insert(0, cannots[-1])
        summary["cannot_verify"] += 1

    clarification = None
    if cannots:
        first = sorted(cannots, key=lambda f: ("REQUEST_NEW_PHOTO" != f.action, f.rule_id))[0]
        fields = {m for f in cannots for m in f.missing}
        # Ask for every unresolved reading at once, so one confirmation round unblocks the case.
        fields |= {k for k, fct in snap.facts.items() if fct.status == "ambiguous" and (k in MANDATORY or k in ("rx.strength", "dispensed.volume_ml"))}
        clarification = {"action": first.action, "fields": sorted(fields), "reason": first.message, "source": "deterministic"}

    snap_hash = snap.sha256()
    blob = json.dumps({"snapshot": snap_hash, "pack": pack.sha256, "engine": ENGINE_VERSION, "state": state,
                       "findings": [f.model_dump(exclude={"source"}) for f in findings]}, sort_keys=True, default=str)
    return Verification(
        state=state,
        summary=summary,
        findings=findings,
        coverage=coverage,
        clarification=clarification,
        snapshot_sha256=snap_hash,
        rulepack=pack.summary_dict(),
        engine=ENGINE_VERSION,
        result_sha256=hashlib.sha256(blob.encode()).hexdigest(),
        evidence={k: v.model_dump() for k, v in snap.graph.nodes.items()},
    )
