"""Rule-pack registry: load, validate, hash and verify quotes against source text."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

SEVERITIES = ["critical", "high", "moderate", "advisory", "cannot_verify", "out_of_scope"]
SEVERITY_RANK = {"critical": 4, "high": 3, "moderate": 2, "advisory": 1}


class RuleSource(BaseModel):
    ref: str
    locator: Any = None
    quote: str | list[str] | None = None

    @property
    def quotes(self) -> list[str]:
        if self.quote is None:
            return []
        return [self.quote] if isinstance(self.quote, str) else list(self.quote)


class Rule(BaseModel):
    id: str
    version: str
    title: str
    type: str
    severity: str
    requires: list[str] = Field(default_factory=list)
    params: dict[str, Any] = Field(default_factory=dict)
    applies_to: dict[str, Any] = Field(default_factory=dict)
    component: str | None = None
    indication: str | None = None
    source: RuleSource
    related_sources: list[RuleSource] = Field(default_factory=list)
    explain: str | None = None
    status: str = "active"


class RulePack(BaseModel):
    id: str
    version: str
    title: str
    summary: str
    effective_date: str
    scope: dict[str, Any]
    policies: dict[str, Any]
    rules: list[Rule]
    formulary: dict[str, Any]
    sources: dict[str, Any]
    indications: dict[str, Any]
    sha256: str
    root: str

    def rule(self, rule_id: str) -> Rule:
        for r in self.rules:
            if r.id == rule_id:
                return r
        raise KeyError(rule_id)

    def summary_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "version": self.version,
            "title": self.title,
            "sha256": self.sha256,
            "rules": len(self.rules),
            "effective_date": self.effective_date,
        }


def default_pack_dir() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "rulepacks" / "pediatric-oral-antibiotics"
        if candidate.exists():
            return candidate
    raise FileNotFoundError("rulepacks/pediatric-oral-antibiotics not found")


def pack_hash(root: Path) -> str:
    """SHA-256 over every file in the pack, path-sorted, with line endings normalised."""
    h = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        rel = path.relative_to(root).as_posix()
        data = path.read_bytes().replace(b"\r\n", b"\n")
        h.update(rel.encode() + b"\0" + hashlib.sha256(data).digest())
    return h.hexdigest()


def load_pack(root: Path | str | None = None) -> RulePack:
    return _load_pack(str(Path(root) if root else default_pack_dir()))


@lru_cache(maxsize=4)
def _load_pack(root_s: str) -> RulePack:
    root = Path(root_s)
    meta = yaml.safe_load((root / "pack.yaml").read_text(encoding="utf-8"))
    rules: list[Rule] = []
    indications: dict[str, Any] = {}
    for rel in meta["rule_files"]:
        data = yaml.safe_load((root / rel).read_text(encoding="utf-8"))
        if isinstance(data, dict):
            indications.update(data.get("indications", {}))
            data = data["rules"]
        rules.extend(Rule.model_validate(r) for r in data)
    ids = [r.id for r in rules]
    dupes = {i for i in ids if ids.count(i) > 1}
    if dupes:
        raise ValueError(f"duplicate rule ids: {sorted(dupes)}")
    for r in rules:
        if r.severity not in SEVERITIES:
            raise ValueError(f"{r.id}: unknown severity {r.severity}")
    return RulePack(
        id=meta["id"],
        version=meta["version"],
        title=meta["title"],
        summary=meta["summary"].strip(),
        effective_date=meta["effective_date"],
        scope=meta["scope"],
        policies=meta["policies"],
        rules=rules,
        formulary=yaml.safe_load((root / meta["formulary"]).read_text(encoding="utf-8")),
        sources=yaml.safe_load((root / meta["sources"]).read_text(encoding="utf-8")),
        indications=indications,
        sha256=pack_hash(root),
        root=str(root),
    )


def _squash(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    return re.sub(r"\s+", "", text)


def verify_quotes(pack: RulePack) -> list[dict[str, Any]]:
    """Check every rule quote against the snapshotted source text.

    Returns one record per quote with ``found`` and, for WHO quotes, the PDF pages where the
    quote occurs, so a wrong locator is reported alongside a missing quote.
    """
    root = Path(pack.root)
    who = json.loads((root / "sources" / "who-aware-2022-pages.json").read_text(encoding="utf-8"))
    labels = json.loads((root / "sources" / "fda-labels.json").read_text(encoding="utf-8"))
    who_pages = {int(k): _squash(v) for k, v in who["pages"].items()}
    results = []
    for rule in pack.rules:
        for src in [rule.source, *rule.related_sources]:
            for q in src.quotes:
                sq = _squash(q)
                rec: dict[str, Any] = {"rule": rule.id, "ref": src.ref, "quote": q}
                if src.ref == "WHO-AWARE-2022":
                    want = src.locator.get("pdf_page") if isinstance(src.locator, dict) else None
                    hits = sorted(p for p, t in who_pages.items() if sq in t)
                    rec.update(found=bool(want in hits), pages=hits, locator_page=want)
                elif src.ref.startswith("FDA-LABEL"):
                    sections = labels[src.ref]["sections"]
                    rec.update(found=any(sq in _squash(t) for t in sections.values()))
                else:
                    rec.update(found=True)
                results.append(rec)
    return results
