"""Deterministic terminology normalisation against the pack formulary.

Aliases match on word boundaries after case folding. A text that resolves to more than one
product, or to an ingredient set that no product has, is returned as unresolved with its
candidates, so a human confirms it. A model never decides what a brand name means.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .rulepack import RulePack
from .units import clean


@dataclass
class Resolution:
    value: str | None
    status: str  # exact | unresolved | unknown
    matched: list[str] = field(default_factory=list)
    candidates: list[str] = field(default_factory=list)
    reason: str | None = None


def _norm(s: str) -> str:
    s = clean(s)
    s = re.sub(r"[®™©]", "", s)
    return s


def _alias_regex(alias: str) -> re.Pattern[str]:
    a = re.escape(_norm(alias)).replace(r"\ ", r"\s*")
    return re.compile(rf"(?<![a-z0-9]){a}(?![a-z0-9])")


class Normalizer:
    def __init__(self, pack: RulePack):
        f = pack.formulary
        self.pack = pack
        self.ingredients: dict[str, dict[str, Any]] = f["ingredients"]
        self.products: dict[str, dict[str, Any]] = f["products"]
        self.forms: dict[str, list[str]] = f["dosage_forms"]
        self.routes: dict[str, list[str]] = f["routes"]
        self.allergens: dict[str, list[str]] = f["allergens"]
        self.recognised_strengths: dict[str, list[list[float]]] = f.get("recognised_liquid_strengths", {})
        self._ing_patterns = [
            (name, alias, _alias_regex(alias)) for name, spec in self.ingredients.items() for alias in spec["aliases"]
        ]
        self._prod_patterns = [
            (name, alias, _alias_regex(alias)) for name, spec in self.products.items() for alias in spec.get("aliases", [])
        ]

    # ------------------------------------------------------------------ products
    def product(self, raw: str) -> Resolution:
        text = _norm(raw)
        if not text:
            return Resolution(None, "unknown", reason="empty")
        # 1. whole-product aliases (brands and combination names)
        prod_hits = {(name, alias) for name, alias, rx in self._prod_patterns if rx.search(text)}
        # 2. ingredient aliases, keeping only the longest alias per span
        ing_spans: list[tuple[int, int, str, str]] = []
        for name, alias, rx in self._ing_patterns:
            for m in rx.finditer(text):
                ing_spans.append((m.start(), m.end(), name, alias))
        ing_spans = [s for s in ing_spans if not any(o[0] <= s[0] and s[1] <= o[1] and (o[1] - o[0]) > (s[1] - s[0]) for o in ing_spans)]
        ing_set = {s[2] for s in ing_spans}
        products_by_ings = [name for name, spec in self.products.items() if set(spec["components"]) == ing_set]
        prod_names = {p for p, _ in prod_hits}
        if len(prod_names) == 1:
            name = prod_names.pop()
            # A brand alias and an ingredient list that contradicts it must not be reconciled here.
            if ing_set and set(self.products[name]["components"]) != ing_set and not ing_set <= set(self.products[name]["components"]):
                return Resolution(None, "unresolved", candidates=[name, *products_by_ings], reason="brand and ingredients disagree")
            return Resolution(name, "exact", matched=sorted(a for _, a in prod_hits))
        if len(prod_names) > 1:
            return Resolution(None, "unresolved", candidates=sorted(prod_names), reason="matches more than one product")
        if len(products_by_ings) == 1:
            # A misspelt second ingredient ("amoxicillin/clavulanolate") must not resolve to the single product.
            leftover = text
            for s in sorted(ing_spans, key=lambda s: -s[0]):
                leftover = leftover[: s[0]] + " " + leftover[s[1]:]
            missed = set(self.near_misses(leftover, cutoff=0.75)) - ing_set - set(products_by_ings)
            missed = {m for m in missed if m in self.ingredients and m not in ing_set} | {
                c for m in missed if m in self.products for c in self.products[m]["components"] if c not in ing_set}
            if missed:
                return Resolution(None, "unresolved", candidates=sorted(missed | ing_set),
                                  reason=f"text also resembles {', '.join(sorted(missed))}")
            return Resolution(products_by_ings[0], "exact", matched=sorted({s[3] for s in ing_spans}))
        if ing_set:
            known = [i for i in ing_set if i in self.ingredients]
            # an ingredient set that is not a pack product (e.g. an unsupported antibiotic combination)
            return Resolution(None, "unknown", candidates=sorted(known), reason="ingredient set is not a product in this pack")
        return Resolution(None, "unknown", reason="no known ingredient or product name")

    def near_misses(self, raw: str, cutoff: float = 0.8) -> list[str]:
        """Product names within a small edit distance of ``raw``: likely misreads, never auto-applied."""
        import difflib

        text = _norm(raw)
        words = re.findall(r"[a-zé][a-zé\-]{3,}", text)
        names: dict[str, str] = {}
        for name, spec in self.ingredients.items():
            for a in spec["aliases"]:
                names[_norm(a)] = name
        for name, spec in self.products.items():
            for a in spec.get("aliases", []):
                names[_norm(a)] = name
        hits: set[str] = set()
        for w in words:
            for m in difflib.get_close_matches(w, list(names), n=3, cutoff=cutoff):
                if m != w:
                    hits.add(names[m])
        return sorted(hits)

    def components(self, product: str) -> list[str]:
        return list(self.products[product]["components"])

    def product_classes(self, product: str) -> set[str]:
        classes = set(self.products[product].get("classes", []))
        for comp in self.products[product]["components"]:
            classes |= set(self.ingredients[comp].get("classes", []))
        return classes

    def display(self, product: str) -> str:
        return " + ".join(self.ingredients[c]["display"] for c in self.components(product)).replace(
            "Sulfamethoxazole + Trimethoprim", "Sulfamethoxazole+trimethoprim"
        )

    # ------------------------------------------------------------------ forms and routes
    def dosage_form(self, raw: str) -> str | None:
        text = _norm(raw)
        best: tuple[int, str] | None = None
        for form, aliases in self.forms.items():
            for alias in aliases:
                m = _alias_regex(alias).search(text)
                if m and (best is None or len(alias) > best[0]):
                    best = (len(alias), form)
        return best[1] if best else None

    def route(self, raw: str) -> str | None:
        text = _norm(raw)
        hits = {r for r, aliases in self.routes.items() for a in aliases if _alias_regex(a).search(text)}
        return hits.pop() if len(hits) == 1 else None

    # ------------------------------------------------------------------ patient terms
    @staticmethod
    def split_list(raw: str) -> list[str]:
        parts = re.split(r"\s*(?:,|;|/|\n|\band\b|\bet\b|\+)\s*", raw or "")
        return [p.strip(" .") for p in parts if p and p.strip(" .")]

    REACTION_WORDS = re.compile(
        r"\b(allergy|allergies|allergic to|allergic|allergie|allergique à|allergique a|intolerance|reaction|rash|hives|"
        r"urticaria|anaphylaxis|severe|mild|history of|known|to|urticaire|éruption|anaphylaxie|sévère)\b"
    )

    def allergy(self, raw: str) -> Resolution:
        text = _norm(raw)
        text = re.sub(r"\(.*?\)", " ", text)
        for cls in ("none",):
            if any(_alias_regex(a).fullmatch(text.strip(" .")) for a in self.allergens[cls]):
                return Resolution(cls, "exact")
        if re.search(r"\b(no|not|denies|pas d'|pas de|sans|aucune?)\b", text):
            return Resolution(None, "unresolved", reason="allergy statement contains a negation")
        core = re.sub(r"\s+", " ", self.REACTION_WORDS.sub(" ", text)).strip(" :-.,")
        exact = {cls for cls, aliases in self.allergens.items() for a in aliases if _alias_regex(a).fullmatch(core)}
        if len(exact) == 1:
            return Resolution(exact.pop(), "exact", matched=[core])
        found = {cls for cls, aliases in self.allergens.items() for a in aliases if _alias_regex(a).search(core)}
        found.discard("none")
        if len(found) == 1:
            return Resolution(found.pop(), "exact", matched=[core])
        if len(found) > 1:
            return Resolution(None, "unresolved", candidates=sorted(found), reason="matches more than one allergen class")
        return Resolution(None, "unknown", reason="allergen term not recognised")

    def medication(self, raw: str) -> Resolution:
        text = _norm(raw)
        prod = self.product(text)
        if prod.status == "exact":
            return prod
        hits = {name for name, alias, rx in self._ing_patterns if rx.search(text)}
        if len(hits) == 1:
            return Resolution(hits.pop(), "exact")
        if len(hits) > 1:
            return Resolution(None, "unresolved", candidates=sorted(hits), reason="matches more than one ingredient")
        return Resolution(None, "unknown", reason="medicine not recognised")

    def med_ingredients(self, value: str) -> list[str]:
        if value in self.products:
            return self.components(value)
        return [value]

    def ingredient_classes(self, ingredient: str) -> set[str]:
        return set(self.ingredients.get(ingredient, {}).get("classes", []))

    def indication(self, raw: str) -> Resolution:
        text = _norm(raw)
        for key, spec in self.pack.indications.items():
            for alias in spec["aliases"]:
                if _alias_regex(alias).search(text):
                    return Resolution(key, "exact", matched=[alias])
        return Resolution(None, "unknown", reason="indication not covered by duration rules")

    def strength_recognised(self, product: str, components_mg: list[float], per_ml: float | None) -> bool | None:
        known = self.recognised_strengths.get(product)
        if known is None or per_ml is None:
            return None
        per5 = [round(c * 5 / per_ml, 3) for c in components_mg]
        return any(len(k) == len(per5) and all(abs(a - b) < 0.01 for a, b in zip(k, per5)) for k in known)
