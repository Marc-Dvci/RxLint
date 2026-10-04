"""Strict local FHIR R4 MedicationRequest import for single fixed oral regimens.

No network resolution, patient identity inference, or authentication claim. The importer
accepts one active order and copies explicit structured values with JSON-path provenance.
Unsupported schedules fail at import instead of becoming a simplified prescription.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from .core.units import Unparseable, parse_dose, parse_duration_days, parse_frequency, parse_strength
from .core import Normalizer, load_pack


class FHIRImportError(ValueError):
    pass


def _number(value: Any) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise FHIRImportError("quantity must contain a finite positive numeric value")
    try:
        v = Decimal(str(value))
    except InvalidOperation:
        raise FHIRImportError("invalid numeric quantity") from None
    if not v.is_finite() or v <= 0:
        raise FHIRImportError("quantity must be finite and positive")
    if v > 1_000_000 or v < Decimal("0.000001"):
        raise FHIRImportError("quantity outside the supported numeric import range")
    return format(v.normalize(), "f")


def _quantity(q: Any, units: set[str]) -> str:
    if not isinstance(q, dict) or q.get("comparator"):
        raise FHIRImportError("a single exact Quantity is required; ranges/comparators are unsupported")
    if q.get("system") not in (None, "http://unitsofmeasure.org"):
        raise FHIRImportError("quantity uses an unsupported unit system")
    unit = q.get("code") or q.get("unit")
    if unit not in units:
        raise FHIRImportError(f"unsupported quantity unit: {unit!r}; supported: {sorted(units)}")
    if q.get("code") and q.get("unit") and q["unit"].lower() != q["code"].lower():
        raise FHIRImportError("Quantity code and displayed unit disagree")
    return f"{_number(q.get('value'))} {unit}"


def _text(concept: Any) -> str | None:
    if not isinstance(concept, dict):
        return None
    text = concept.get("text")
    if isinstance(text, str) and text.strip():
        return text.strip()
    displays = {c["display"].strip() for c in concept.get("coding", [])
                if isinstance(c, dict) and isinstance(c.get("display"), str) and c["display"].strip()}
    if len(displays) == 1:
        return next(iter(displays))
    return None


def import_prescription(payload: dict[str, Any], asset_id: str = "fhir") -> list[dict[str, Any]]:
    """Convert supported orders, with consistent errors for malformed nested FHIR data."""
    def check_modifiers(value):
        if isinstance(value, dict):
            if value.get("modifierExtension"):
                raise FHIRImportError("modifier extensions require an integration that understands their meaning")
            for child in value.values():
                check_modifiers(child)
        elif isinstance(value, list):
            for child in value:
                check_modifiers(child)
    try:
        check_modifiers(payload)
        return _import_prescription(payload, asset_id)
    except (TypeError, AttributeError, KeyError, RecursionError) as exc:
        raise FHIRImportError("malformed nested FHIR resource; expected standard R4 objects and arrays") from exc


def _import_prescription(payload: dict[str, Any], asset_id: str) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        raise FHIRImportError("FHIR input must be an object")
    resources: dict[str, dict] = {}
    if payload.get("resourceType") == "Bundle":
        entries = payload.get("entry")
        if not isinstance(entries, list):
            raise FHIRImportError("Bundle.entry must be an array")
        orders = []
        for i, entry in enumerate(entries):
            if not isinstance(entry, dict) or not isinstance(entry.get("resource"), dict):
                raise FHIRImportError("each Bundle entry must contain a resource")
            r = entry["resource"]
            if r.get("resourceType") == "MedicationRequest":
                orders.append((r, f"$.entry[{i}].resource"))
            for key in (entry.get("fullUrl"), f"{r.get('resourceType')}/{r['id']}" if r.get("id") else None):
                if key:
                    if key in resources:
                        raise FHIRImportError("duplicate resource reference in Bundle")
                    resources[key] = r
        if len(orders) != 1:
            raise FHIRImportError("provide exactly one MedicationRequest")
        request, path = orders[0]
    elif payload.get("resourceType") == "MedicationRequest":
        request, path = payload, "$"
    else:
        raise FHIRImportError("expected a MedicationRequest or Bundle")
    if request.get("status") != "active" or request.get("intent") != "order" or request.get("doNotPerform"):
        raise FHIRImportError("only active medication orders can be imported")
    for resource in request.get("contained", []):
        if not isinstance(resource, dict) or not resource.get("id"):
            raise FHIRImportError("contained resources need an id")
        key = f"#{resource['id']}"
        if key in resources:
            raise FHIRImportError("duplicate contained resource id")
        resources[key] = resource
    obs = []

    def add(field: str, value: str | None, source: str):
        if value:
            obs.append({"field": field, "text": value, "asset_id": asset_id,
                        "kind": "STRUCTURED_PRESCRIPTION", "method": "fhir-r4-import",
                        "source_path": source, "legible": True, "requires_confirmation": False})

    medication = None
    if "medicationReference" in request and "medicationCodeableConcept" in request:
        raise FHIRImportError("supply exactly one medication choice")
    if "medicationReference" in request:
        ref = request["medicationReference"].get("reference")
        medication = resources.get(ref)
        if not medication or medication.get("resourceType") != "Medication":
            raise FHIRImportError("medicationReference must resolve to a Medication included in this input")
        name = _text(medication.get("code"))
        form = _text(medication.get("form"))
        add("rx.drug", " ".join(x for x in (name, form) if x), f"{path}.medicationReference -> {ref}.code/form")
        ingredients = medication.get("ingredient", [])
        if ingredients:
            n = Normalizer(load_pack())
            product = n.product(name or "")
            if product.status != "exact":
                raise FHIRImportError("structured strengths require a medication identified in the current formulary")
            expected = n.components(product.value)
            by_ingredient = {}
            for ing in ingredients:
                if not isinstance(ing, dict):
                    raise FHIRImportError("ingredient must be an object")
                if ing.get("isActive") is False:
                    continue
                label = _text(ing.get("itemCodeableConcept"))
                matched = [key for key, spec in n.ingredients.items()
                           if label and label.casefold() in {a.casefold() for a in spec["aliases"]}]
                if len(matched) != 1 or matched[0] in by_ingredient:
                    raise FHIRImportError("each active ingredient needs a unique recognized name")
                by_ingredient[matched[0]] = ing
            if set(by_ingredient) != set(expected):
                raise FHIRImportError("medication name and active ingredient list disagree")
            ingredients = [by_ingredient[key] for key in expected]
            amounts = []
            denominators = []
            for ing in ingredients:
                if ing.get("isActive") is False:
                    continue
                ratio = ing.get("strength")
                if not isinstance(ratio, dict):
                    raise FHIRImportError("each active ingredient must specify strength as a Ratio")
                amounts.append(_quantity(ratio.get("numerator"), {"mg", "g", "mcg"}))
                denominators.append(_quantity(ratio.get("denominator"), {"mL", "ml"}))
            if len(set(denominators)) != 1 or not amounts:
                raise FHIRImportError("ingredient concentrations need one shared volume denominator")
            strength = f"{'/'.join(amounts)} per {denominators[0]}"
            add("rx.strength", strength, f"{path}.medicationReference -> {ref}.ingredient[*].strength")
    else:
        add("rx.drug", _text(request.get("medicationCodeableConcept")), f"{path}.medicationCodeableConcept")
    if not any(o["field"] == "rx.drug" for o in obs):
        raise FHIRImportError("an explicit medication name is required")
    dosages = request.get("dosageInstruction")
    if not isinstance(dosages, list) or len(dosages) != 1 or not isinstance(dosages[0], dict):
        raise FHIRImportError("exactly one fixed dosageInstruction is supported")
    d = dosages[0]
    dp = f"{path}.dosageInstruction[0]"
    if set(d) - {"id", "sequence", "route", "timing", "doseAndRate", "asNeededBoolean"}:
        raise FHIRImportError("free-text, dose limits and additional dosage conditions are unsupported")
    if "asNeededBoolean" in d and not isinstance(d["asNeededBoolean"], bool):
        raise FHIRImportError("asNeededBoolean must be boolean")
    if d.get("asNeededBoolean") or "asNeededCodeableConcept" in d or d.get("additionalInstruction"):
        raise FHIRImportError("as-needed and additional conditional instructions are unsupported")
    dose_rates = d.get("doseAndRate")
    if not isinstance(dose_rates, list) or len(dose_rates) != 1 or not isinstance(dose_rates[0], dict):
        raise FHIRImportError("one exact doseAndRate is required")
    if set(dose_rates[0]) - {"type", "doseQuantity"}:
        raise FHIRImportError("dose ranges and administration rates are unsupported")
    if dose_rates[0].get("type"):
        coding = dose_rates[0]["type"].get("coding", [])
        if (len(coding) != 1 or coding[0].get("code") != "ordered"
                or coding[0].get("system") != "http://terminology.hl7.org/CodeSystem/dose-rate-type"):
            raise FHIRImportError("doseAndRate.type must identify an ordered dose")
    add("rx.dose", _quantity(dose_rates[0].get("doseQuantity"), {"mL", "ml", "mg", "g", "mcg"}), f"{dp}.doseAndRate[0].doseQuantity")
    timing = d.get("timing", {})
    repeat = timing.get("repeat", {})
    if (not isinstance(repeat, dict) or set(repeat) - {"frequency", "period", "periodUnit", "boundsDuration"}
            or set(timing) - {"repeat"}):
        raise FHIRImportError("only fixed daily/hourly repeat schedules are supported")
    f, p = _number(repeat.get("frequency")), _number(repeat.get("period"))
    unit = repeat.get("periodUnit")
    if unit == "d" and Decimal(p) == 1 and Decimal(f) == int(Decimal(f)):
        frequency = f"{f} times per day"
    elif unit == "h" and Decimal(f) == 1 and Decimal(p) == int(Decimal(p)):
        frequency = f"every {p} hours"
    else:
        raise FHIRImportError("unsupported repeat schedule; use frequency per one day or once per integer hours")
    add("rx.frequency", frequency, f"{dp}.timing.repeat")
    if "boundsDuration" in repeat:
        duration = _quantity(repeat["boundsDuration"], {"d"}).replace(" d", " days")
        add("rx.duration", duration, f"{dp}.timing.repeat.boundsDuration")
    add("rx.route", _text(d.get("route")), f"{dp}.route")
    reasons = request.get("reasonCode", [])
    if len(reasons) == 1:
        add("rx.indication", _text(reasons[0]), f"{path}.reasonCode[0]")
    for o in obs:
        parser = {"rx.dose": parse_dose, "rx.frequency": parse_frequency,
                  "rx.duration": parse_duration_days, "rx.strength": parse_strength}.get(o["field"])
        if parser:
            try:
                parser(o["text"])
            except Unparseable as exc:
                raise FHIRImportError(f"{o['source_path']}: {exc.reason}") from None
    return obs
