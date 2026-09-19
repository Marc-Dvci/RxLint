"""Deterministic RxLint kernel: units, evidence, rule packs and the verifier."""

from .engine import ENGINE_VERSION, Finding, Verification, verify
from .evidence import Evidence, EvidenceGraph, EvidenceKind
from .normalize import Normalizer
from .rulepack import RulePack, load_pack
from .snapshot import Observation, Snapshot, SnapshotBuilder

__all__ = [
    "ENGINE_VERSION", "Evidence", "EvidenceGraph", "EvidenceKind", "Finding", "Normalizer", "Observation",
    "RulePack", "Snapshot", "SnapshotBuilder", "Verification", "load_pack", "verify", "build_snapshot",
]


def build_snapshot(fields: dict, pack: RulePack | None = None, case_id: str = "case", dispense_date=None,
                   kind: EvidenceKind = EvidenceKind.USER_ENTERED_FACT) -> Snapshot:
    """Build a snapshot from ``{field: raw}`` pairs, e.g. for typed entry or tests."""
    from datetime import date

    pack = pack or load_pack()
    b = SnapshotBuilder(Normalizer(pack), case_id)
    for field, raw in fields.items():
        for r in raw if isinstance(raw, list) else [raw]:
            b.add(Observation(field=field, raw=r, kind=kind, method="typed"))
    if isinstance(dispense_date, str):
        dispense_date = date.fromisoformat(dispense_date)
    return b.build(dispense_date=dispense_date)
