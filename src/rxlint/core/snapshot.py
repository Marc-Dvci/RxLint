"""Build the kernel's input: a case snapshot of typed facts, each tied to evidence.

Observations arrive as raw text (what a model transcribed, what a person typed or said). The
builder parses each one with the strict unit grammar, reconciles repeated observations of the
same fact, and records a NORMALIZED_ENTITY evidence node whose parents are the observations.
Disagreeing observations make the fact ``ambiguous``; they are never averaged or picked between.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date
from decimal import Decimal
from typing import Any, Callable

from pydantic import BaseModel, Field

from .evidence import Evidence, EvidenceGraph, EvidenceKind, SourceRef
from .normalize import Normalizer
from .units import (
    manufacturer_name,
    Unparseable,
    parse_age_months,
    parse_dose,
    parse_duration_days,
    parse_expiry,
    parse_frequency,
    parse_lot,
    parse_strength,
    parse_volume_ml,
    parse_weight_kg,
)

MANDATORY = [
    "rx.product",
    "rx.dose",
    "rx.frequency",
    "rx.duration_days",
    "dispensed.product",
    "dispensed.strength",
    "dispensed.expiry",
    "patient.weight_kg",
    "patient.age_months",
    "patient.allergies",
    "patient.current_medications",
    "context.dispense_date",
]
OPTIONAL = {
    "rx.indication",
    "rx.strength",
    "rx.route",
    "rx.dosage_form",
    "dispensed.lot",
    "dispensed.manufacturer",
    "dispensed.product_name",
    "dispensed.dosage_form",
    "dispensed.volume_ml",
    "dispensed.gtin",
    "context.country",
}

# Numeric fields whose model-reported confidence must clear a stricter bar (policy P-PERC-01).
HIGH_RISK_FIELDS = {"rx.strength", "rx.dose", "rx.frequency", "dispensed.strength", "patient.weight_kg", "rx.duration_days"}
HIGH_RISK_MIN_CONFIDENCE = 0.80


class Observation(BaseModel):
    """One raw reading of one field, before any parsing."""

    field: str  # e.g. "rx.drug", "dispensed.strength", "patient.weight"
    raw: str
    kind: EvidenceKind = EvidenceKind.VISUAL_OBSERVATION
    asset_id: str | None = None
    bbox: list[float] | None = None
    grounding: str | None = None
    method: str | None = None
    confidence: float | None = None
    legible: bool = True
    alternatives: list[str] = Field(default_factory=list)
    requires_confirmation: bool = False  # policy P-PERC-02: no independent reader agreed


class Fact(BaseModel):
    status: str = "missing"  # present | missing | ambiguous
    value: Any = None
    evidence: str | None = None
    raw: str | None = None
    reason: str | None = None
    candidates: list[str] = Field(default_factory=list)
    derived: bool = False


class Snapshot(BaseModel):
    case_id: str
    facts: dict[str, Fact]
    graph: EvidenceGraph

    def fact(self, key: str) -> Fact:
        return self.facts.get(key) or Fact()

    def canonical(self) -> dict[str, Any]:
        return {k: {"status": f.status, "value": f.value} for k, f in sorted(self.facts.items())}

    def sha256(self) -> str:
        blob = json.dumps(self.canonical(), sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(blob.encode()).hexdigest()


# Input field name -> canonical fact key
FIELD_MAP = {
    "rx.drug": "rx.product",
    "rx.product": "rx.product",
    "rx.strength": "rx.strength",
    "rx.dosage_form": "rx.dosage_form",
    "rx.route": "rx.route",
    "rx.dose": "rx.dose",
    "rx.frequency": "rx.frequency",
    "rx.duration": "rx.duration_days",
    "rx.indication": "rx.indication",
    "rx.patient_weight": "patient.weight_kg",
    "rx.patient_age": "patient.age_months",
    "rx.allergies": "patient.allergies",
    "dispensed.drug": "dispensed.product",
    "dispensed.product": "dispensed.product",
    "dispensed.strength": "dispensed.strength",
    "dispensed.dosage_form": "dispensed.dosage_form",
    "dispensed.volume": "dispensed.volume_ml",
    "dispensed.lot": "dispensed.lot",
    "dispensed.expiry": "dispensed.expiry",
    "dispensed.manufacturer": "dispensed.manufacturer",
    "dispensed.product_name": "dispensed.product_name",
    "dispensed.gtin": "dispensed.gtin",
    "patient.weight": "patient.weight_kg",
    "patient.age": "patient.age_months",
    "patient.allergies": "patient.allergies",
    "patient.medications": "patient.current_medications",
    "patient.indication": "rx.indication",
    "context.dispense_date": "context.dispense_date",
    "context.country": "context.country",
}


def _parse_gtin(raw: str) -> str:
    digits = "".join(ch for ch in raw if ch.isdigit())
    if len(digits) not in (8, 12, 13, 14):
        raise Unparseable("gtin", raw, "not an 8, 12, 13 or 14 digit product code")
    return digits


def _dec(d: Decimal) -> str:
    return format(d.normalize(), "f")


class SnapshotBuilder:
    def __init__(self, normalizer: Normalizer, case_id: str):
        self.n = normalizer
        self.case_id = case_id
        self.graph = EvidenceGraph()
        self.obs: dict[str, list[tuple[Observation, str]]] = {}
        self._counter = 0

    def _id(self, prefix: str) -> str:
        self._counter += 1
        return f"ev_{prefix}_{self._counter:03d}"

    def add(self, ob: Observation) -> str:
        key = FIELD_MAP.get(ob.field)
        if key is None:
            raise KeyError(f"unknown observation field {ob.field}")
        status = "observed" if ob.legible else "ambiguous"
        if ob.kind == EvidenceKind.USER_ENTERED_FACT:
            status = "entered"
        ev = self.graph.add(
            Evidence(
                id=self._id("obs"),
                kind=ob.kind,
                name=ob.field,
                raw=ob.raw,
                value=ob.raw,
                status=status,
                source=SourceRef(asset_id=ob.asset_id, bbox=ob.bbox, grounding=ob.grounding),
                method=ob.method,
                confidence=ob.confidence,
                notes=[f"alternative reading: {a}" for a in ob.alternatives],
            )
        )
        self.obs.setdefault(key, []).append((ob, ev.id))
        return ev.id

    # ------------------------------------------------------------------ reconciliation
    def _reconcile(self, key: str, parser: Callable[[str], Any], render: Callable[[Any], Any]) -> Fact:
        items = self.obs.get(key, [])
        if not items:
            return Fact()
        parsed: list[tuple[Any, Observation, str]] = []
        problems: list[str] = []
        confirmed = [(ob, ev) for ob, ev in items if ob.method == "confirmation"]
        superseded = []
        if confirmed:
            # A pharmacist's confirmation supersedes machine readings of the same field; they stay as parents.
            superseded = [ev for ob, ev in items if ob.method != "confirmation"]
            items_to_parse = confirmed
        else:
            items_to_parse = items
        key_of = lambda v: json.dumps(render(v), sort_keys=True, default=str)
        readings: list[tuple[Observation, str, Any, str | None]] = []  # (obs, ev, value, error)
        for ob, ev_id in items_to_parse:
            try:
                readings.append((ob, ev_id, parser(ob.raw), None))
            except Unparseable as exc:
                readings.append((ob, ev_id, None, f"{ob.field}: {exc.reason} ({ob.raw!r})"))
        if key in ("rx.product", "dispensed.product") and any(err is None for *_, err in readings):
            # A name reading that resolves to no product carries no evidence when another reader resolved it.
            readings = [r for r in readings if r[3] is None]

        def corroborated(ob: Observation, value: Any) -> bool:
            """Another source (a different reader, a typed entry or a confirmation) agrees on the value."""
            k = key_of(value)
            return any(o is not ob and err is None and (o.kind != ob.kind or o.method != ob.method) and key_of(v) == k
                       for o, _, v, err in readings)

        for ob, ev_id, value, err in readings:
            if not ob.legible:
                problems.append(f"{ob.field} marked illegible in {ob.asset_id or 'input'}")
                continue
            if err is not None:
                problems.append(err)
                continue
            conflicting = []
            for alt in ob.alternatives:
                try:
                    if key_of(parser(alt)) != key_of(value):
                        conflicting.append(alt)
                except Unparseable:
                    conflicting.append(alt)
            if conflicting:
                problems.append(f"{ob.field} has competing readings: {', '.join([ob.raw, *conflicting])}")
                continue
            if ob.requires_confirmation and not corroborated(ob, value):
                problems.append(f"{ob.field} '{ob.raw}' was not corroborated by an independent reader (P-PERC-02); confirm the value")
                continue
            if (
                key in HIGH_RISK_FIELDS
                and ob.kind == EvidenceKind.VISUAL_OBSERVATION
                and ob.confidence is not None
                and ob.confidence < HIGH_RISK_MIN_CONFIDENCE
                and not corroborated(ob, value)
            ):
                problems.append(f"{ob.field} read with confidence {ob.confidence:.2f} (< {HIGH_RISK_MIN_CONFIDENCE}, P-PERC-01)")
                continue
            parsed.append((value, ob, ev_id))
        parents = [ev for _, ev in items]
        raw = " | ".join(ob.raw for ob, _ in items)
        if problems:
            return self._ambiguous(key, parents, raw, "; ".join(problems))
        values = {json.dumps(render(v), sort_keys=True, default=str) for v, _, _ in parsed}
        if len(values) > 1:
            shown = " vs ".join(f"{ob.raw!r} ({ob.asset_id or ob.kind.value.lower()})" for _, ob, _ in parsed)
            return self._ambiguous(key, parents, raw, f"sources disagree: {shown}", candidates=sorted(values))
        value = render(parsed[0][0])
        ev = self.graph.add(
            Evidence(
                id=f"ev_{key.replace('.', '_')}",
                kind=EvidenceKind.NORMALIZED_ENTITY,
                name=key,
                value=value,
                raw=raw,
                status="normalized",
                method="rxlint.units",
                parents=parents,
                notes=(["confirmed by the pharmacist; machine readings superseded"] if superseded
                       else ["corroborated by independent sources"] if len(parents) > 1 else []),
            )
        )
        return Fact(status="present", value=value, evidence=ev.id, raw=raw)

    def _ambiguous(self, key: str, parents: list[str], raw: str, reason: str, candidates: list[str] | None = None) -> Fact:
        ev = self.graph.add(
            Evidence(
                id=f"ev_{key.replace('.', '_')}",
                kind=EvidenceKind.NORMALIZED_ENTITY,
                name=key,
                raw=raw,
                status="ambiguous",
                method="rxlint.units",
                parents=parents,
                notes=[reason],
            )
        )
        return Fact(status="ambiguous", evidence=ev.id, raw=raw, reason=reason, candidates=candidates or [])

    def _derived(self, key: str, value: Any, parent: str, note: str) -> Fact:
        ev = self.graph.add(
            Evidence(
                id=f"ev_{key.replace('.', '_')}",
                kind=EvidenceKind.NORMALIZED_ENTITY,
                name=key,
                value=value,
                status="derived",
                method="rxlint.normalize",
                parents=[parent],
                notes=[note],
            )
        )
        return Fact(status="present", value=value, evidence=ev.id, derived=True, reason=note)

    # ------------------------------------------------------------------ parsers
    def _product(self, raw: str) -> str:
        res = self.n.product(raw)
        if res.status != "exact":
            raise Unparseable("product", raw, res.reason or "not resolved")
        return res.value  # type: ignore[return-value]

    def _form(self, raw: str) -> str:
        form = self.n.dosage_form(raw)
        if form is None:
            raise Unparseable("dosage_form", raw, "dosage form not recognised")
        return form

    def _route(self, raw: str) -> str:
        r = self.n.route(raw)
        if r is None:
            raise Unparseable("route", raw, "route not recognised")
        return r

    # ------------------------------------------------------------------ build
    def build(self, dispense_date: date | None = None) -> Snapshot:
        facts: dict[str, Fact] = {}
        strength_render = lambda s: {
            "components_mg": [_dec(c) for c in s.components_mg],
            "per_ml": _dec(s.per_ml) if s.per_ml is not None else None,
            "per_unit": s.per_unit,
        }
        dose_render = lambda d: {
            "volume_ml": _dec(d.volume_ml) if d.volume_ml is not None else None,
            "mass_mg": _dec(d.mass_mg) if d.mass_mg is not None else None,
            "units": _dec(d.units) if d.units is not None else None,
            "unit_name": d.unit_name,
        }
        freq_render = lambda f: {"per_day": _dec(f.per_day), "interval_h": _dec(f.interval_h) if f.interval_h else None, "label": f.label}
        identity = lambda v: v
        dec_render = lambda d: _dec(d)

        specs: dict[str, tuple[Callable[[str], Any], Callable[[Any], Any]]] = {
            "rx.product": (self._product, identity),
            "dispensed.product": (self._product, identity),
            "rx.strength": (parse_strength, strength_render),
            "dispensed.strength": (parse_strength, strength_render),
            "rx.dosage_form": (self._form, identity),
            "dispensed.dosage_form": (self._form, identity),
            "rx.route": (self._route, identity),
            "rx.dose": (parse_dose, dose_render),
            "rx.frequency": (parse_frequency, freq_render),
            "rx.duration_days": (parse_duration_days, dec_render),
            "dispensed.volume_ml": (parse_volume_ml, dec_render),
            "dispensed.lot": (parse_lot, identity),
            "dispensed.expiry": (parse_expiry, lambda d: d.isoformat()),
            "patient.weight_kg": (parse_weight_kg, dec_render),
            "patient.age_months": (parse_age_months, dec_render),
            "dispensed.manufacturer": (manufacturer_name, identity),
            "dispensed.product_name": (lambda s: s.strip(), identity),
            "dispensed.gtin": (_parse_gtin, identity),
            "context.country": (lambda s: s.strip().upper()[:2], identity),
        }
        for key, (parser, render) in specs.items():
            facts[key] = self._reconcile(key, parser, render)

        for key in ("rx.product", "dispensed.product"):
            facts[key] = self._classify_product(key, facts[key])
        facts["rx.indication"] = self._indication()
        facts["patient.allergies"] = self._allergies()
        facts["patient.current_medications"] = self._medications()

        # Dosage form: stated, else derived from the product text, else from the dose unit.
        for side in ("rx", "dispensed"):
            key = f"{side}.dosage_form"
            if facts[key].status == "missing":
                facts[key] = self._derive_form(side, facts)
        if facts["rx.route"].status == "missing" and facts["rx.dosage_form"].status == "present":
            if facts["rx.dosage_form"].value in ("oral_liquid", "tablet", "capsule"):
                facts["rx.route"] = self._derived(
                    "rx.route", "oral", facts["rx.dosage_form"].evidence, "route derived from an oral dosage form"
                )

        dd = self.obs.get("context.dispense_date")
        if dd:
            facts["context.dispense_date"] = self._reconcile("context.dispense_date", lambda s: date.fromisoformat(s.strip()), lambda d: d.isoformat())
        else:
            today = (dispense_date or date.today()).isoformat()
            ev = self.graph.add(
                Evidence(id="ev_context_dispense_date", kind=EvidenceKind.USER_ENTERED_FACT, name="context.dispense_date",
                         value=today, raw=today, status="entered", method="system clock")
            )
            facts["context.dispense_date"] = Fact(status="present", value=today, evidence=ev.id, raw=today)
        return Snapshot(case_id=self.case_id, facts=facts, graph=self.graph)

    def _classify_product(self, key: str, fact: Fact) -> Fact:
        """Split unresolved product text into a likely misread (ambiguous) or a different medicine."""
        if fact.status != "ambiguous":
            return fact
        items = self.obs.get(key, [])
        if any(not ob.legible or ob.alternatives for ob, _ in items):
            return fact
        resolutions = [self.n.product(ob.raw) for ob, _ in items]
        if any(r.status == "exact" for r in resolutions) or any(r.status == "unresolved" for r in resolutions):
            return fact
        near = sorted({c for ob, _ in items for c in self.n.near_misses(ob.raw)})
        node = self.graph.nodes[fact.evidence]
        if near:
            node.notes.append(f"close to {', '.join(near)}: confirm the name")
            return fact.model_copy(update={"candidates": near, "reason": f"name not recognised; close to {', '.join(near)}"})
        node.status = "unrecognised"
        node.notes.append("not a product of this pack")
        return fact.model_copy(update={"status": "unrecognised", "reason": "not a product of this pack"})

    def _derive_form(self, side: str, facts: dict[str, Fact]) -> Fact:
        key = f"{side}.dosage_form"
        texts = self.obs.get(f"{side}.product", []) + self.obs.get(f"{side}.strength", [])
        forms = {self.n.dosage_form(ob.raw) for ob, _ in texts} - {None}
        if len(forms) == 1:
            parent = next(ev for ob, ev in texts if self.n.dosage_form(ob.raw))
            return self._derived(key, forms.pop(), parent, "dosage form read from the product text")
        if side == "rx" and facts["rx.dose"].status == "present":
            dose = facts["rx.dose"].value
            if dose.get("volume_ml"):
                return self._derived(key, "oral_liquid", facts["rx.dose"].evidence, "liquid form implied by a volume dose")
            if dose.get("unit_name"):
                form = "capsule" if dose["unit_name"].startswith(("cap", "gél")) else "tablet"
                return self._derived(key, form, facts["rx.dose"].evidence, "solid form implied by a unit dose")
        if side == "dispensed" and facts["dispensed.strength"].status == "present":
            s = facts["dispensed.strength"].value
            if s.get("per_ml"):
                return self._derived(key, "oral_liquid", facts["dispensed.strength"].evidence, "liquid form implied by a per-mL strength")
        return Fact()

    def _list_fact(self, key: str, resolver: Callable[[str], Any], empty_class: str | None) -> Fact:
        all_items = self.obs.get(key, [])
        if not all_items:
            return Fact()
        confirmed = [(ob, ev) for ob, ev in all_items if ob.method == "confirmation"]
        items = confirmed or all_items
        entries: list[dict[str, Any]] = []
        for ob, ev_id in items:
            if not ob.legible:
                entries.append({"raw": ob.raw, "value": None, "status": "illegible", "evidence": ev_id})
                continue
            parts = Normalizer.split_list(ob.raw) or [ob.raw]
            for part in parts:
                res = resolver(part)
                entries.append({"raw": part, "value": res.value, "status": res.status, "candidates": res.candidates,
                                "reason": res.reason, "evidence": ev_id})
        if empty_class is not None:
            informative = [e for e in entries if e["value"] != empty_class]
            if entries and not informative:
                entries = []
        value = entries
        ev = self.graph.add(
            Evidence(id=f"ev_{key.replace('.', '_')}", kind=EvidenceKind.NORMALIZED_ENTITY, name=key, value=value,
                     raw=" | ".join(ob.raw for ob, _ in items), status="normalized", method="rxlint.normalize",
                     parents=[ev for _, ev in all_items],
                     notes=["confirmed by the pharmacist; other readings superseded"] if confirmed else [])
        )
        return Fact(status="present", value=value, evidence=ev.id, raw=" | ".join(ob.raw for ob, _ in items))

    def _allergies(self) -> Fact:
        return self._list_fact("patient.allergies", self.n.allergy, "none")

    def _medications(self) -> Fact:
        def resolve(part: str):
            if part.strip().lower() in {"none", "no", "nil", "aucun", "aucune", "no other medicines", "none known"}:
                from .normalize import Resolution

                return Resolution("none", "exact")
            return self.n.medication(part)

        return self._list_fact("patient.current_medications", resolve, "none")

    def _indication(self) -> Fact:
        items = self.obs.get("rx.indication", [])
        if not items:
            return Fact()
        resolved = {self.n.indication(ob.raw).value for ob, _ in items}
        if len(resolved) > 1 and None in resolved:
            resolved.discard(None)  # an unrecognised reading carries no evidence when another reader resolved it
        parents = [ev for _, ev in items]
        raw = " | ".join(ob.raw for ob, _ in items)
        if len(resolved) == 1 and None not in resolved:
            value = resolved.pop()
            ev = self.graph.add(Evidence(id="ev_rx_indication", kind=EvidenceKind.NORMALIZED_ENTITY, name="rx.indication",
                                         value=value, raw=raw, status="normalized", method="rxlint.normalize", parents=parents))
            return Fact(status="present", value=value, evidence=ev.id, raw=raw)
        ev = self.graph.add(Evidence(id="ev_rx_indication", kind=EvidenceKind.NORMALIZED_ENTITY, name="rx.indication",
                                     raw=raw, status="unrecognised", method="rxlint.normalize", parents=parents,
                                     notes=["indication not covered by the duration rules"]))
        return Fact(status="unrecognised", evidence=ev.id, raw=raw, reason="indication not covered by the duration rules")
