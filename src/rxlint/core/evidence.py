"""Evidence graph: every fact the kernel uses, and where it came from.

A clinical finding may only cite evidence that exists in the graph, and every piece of
evidence is either primary (pixels, a spoken or typed statement) or derived from parents.
``trace`` walks from any node back to its primary sources.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class EvidenceKind(str, Enum):
    VISUAL_OBSERVATION = "VISUAL_OBSERVATION"
    SPOKEN_OBSERVATION = "SPOKEN_OBSERVATION"
    USER_ENTERED_FACT = "USER_ENTERED_FACT"
    BARCODE_LOOKUP = "BARCODE_LOOKUP"
    NORMALIZED_ENTITY = "NORMALIZED_ENTITY"
    DERIVED_CALCULATION = "DERIVED_CALCULATION"
    RULE_SOURCE = "RULE_SOURCE"
    RULE_RESULT = "RULE_RESULT"
    LIVE_WEB_SOURCE = "LIVE_WEB_SOURCE"
    REGULATORY_ALERT = "REGULATORY_ALERT"
    RULE_SOURCE_DRIFT = "RULE_SOURCE_DRIFT"
    MODEL_EXPLANATION = "MODEL_EXPLANATION"


PRIMARY_KINDS = {
    EvidenceKind.VISUAL_OBSERVATION,
    EvidenceKind.SPOKEN_OBSERVATION,
    EvidenceKind.USER_ENTERED_FACT,
    EvidenceKind.BARCODE_LOOKUP,
    EvidenceKind.LIVE_WEB_SOURCE,
}


class SourceRef(BaseModel):
    asset_id: str | None = None
    bbox: list[float] | None = None  # normalised [x0, y0, x1, y1] in 0..1
    grounding: str | None = None  # how the bbox was obtained
    span: str | None = None  # quoted span for text sources


class Evidence(BaseModel):
    id: str
    kind: EvidenceKind
    name: str
    value: Any = None
    unit: str | None = None
    raw: str | None = None
    status: str = "observed"  # observed | normalized | derived | entered | ambiguous | rejected
    source: SourceRef | None = None
    method: str | None = None  # extractor, parser or engine identifier
    confidence: float | None = None
    formula: str | None = None
    parents: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"))


class EvidenceGraph(BaseModel):
    nodes: dict[str, Evidence] = Field(default_factory=dict)

    def add(self, ev: Evidence) -> Evidence:
        for p in ev.parents:
            if p not in self.nodes:
                raise KeyError(f"evidence {ev.id} cites unknown parent {p}")
        self.nodes[ev.id] = ev
        return ev

    def get(self, ev_id: str) -> Evidence:
        return self.nodes[ev_id]

    def trace(self, ev_id: str) -> list[str]:
        """Return the ids on every path from ``ev_id`` back to primary evidence."""
        seen: list[str] = []
        stack = [ev_id]
        while stack:
            cur = stack.pop()
            if cur in seen:
                continue
            seen.append(cur)
            stack.extend(self.nodes[cur].parents)
        return seen

    def primaries(self, ev_id: str) -> list[str]:
        return [i for i in self.trace(ev_id) if self.nodes[i].kind in PRIMARY_KINDS]

    def is_grounded(self, ev_id: str) -> bool:
        """A node is grounded when every leaf reached from it is primary evidence."""
        for node_id in self.trace(ev_id):
            node = self.nodes[node_id]
            if not node.parents and node.kind not in PRIMARY_KINDS and node.kind != EvidenceKind.RULE_SOURCE:
                return False
        return True
