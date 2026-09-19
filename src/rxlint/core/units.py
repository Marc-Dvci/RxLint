"""Strict unit grammar for medication facts.

Every parser takes the raw text a human or a model transcribed and returns a typed value,
or raises :class:`Unparseable`. Parsers never guess: an expression that admits two readings
("1 spoon", "q6-8h", "2.5 or 7.5 mL") is rejected so the caller can report CANNOT_VERIFY.

All arithmetic uses :class:`decimal.Decimal` so a calculation trace reproduces exactly.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation

MASS_TO_MG = {
    "mg": Decimal(1),
    "g": Decimal(1000),
    "gm": Decimal(1000),
    "mcg": Decimal("0.001"),
    "ug": Decimal("0.001"),
    "µg": Decimal("0.001"),
    "μg": Decimal("0.001"),
}
VOLUME_TO_ML = {"ml": Decimal(1), "cc": Decimal(1), "l": Decimal(1000)}
LB_TO_KG = Decimal("0.45359237")


class Unparseable(ValueError):
    """Raised when raw text does not resolve to exactly one typed value."""

    def __init__(self, field: str, raw: str, reason: str):
        super().__init__(f"{field}: {reason} ({raw!r})")
        self.field = field
        self.raw = raw
        self.reason = reason


def clean(raw: str) -> str:
    """NFKC-normalise, fold confusables, lowercase and collapse whitespace."""
    text = unicodedata.normalize("NFKC", raw or "")
    text = (
        text.replace("–", "-")
        .replace("—", "-")
        .replace("−", "-")
        .replace("×", "x")
        .replace("⁄", "/")
        .replace("∕", "/")
    )
    text = text.lower()
    # Latin letters that are commonly swapped for Cyrillic or Greek look-alikes.
    confusables = {"о": "o", "а": "a", "е": "e", "с": "c", "м": "m", "і": "i", "ⅼ": "l"}
    text = "".join(confusables.get(ch, ch) for ch in text)
    return re.sub(r"\s+", " ", text).strip()


def to_decimal(token: str, field: str = "number") -> Decimal:
    """Parse a number that may use a decimal comma. Thousands separators are rejected."""
    t = token.strip()
    if re.fullmatch(r"\d+,\d{1,2}", t):
        t = t.replace(",", ".")
    if not re.fullmatch(r"\d+(\.\d+)?|\.\d+", t):
        raise Unparseable(field, token, "not a plain decimal number")
    if t.startswith("."):
        # A naked leading decimal point is a classic ten-fold error source.
        raise Unparseable(field, token, "leading decimal point without zero")
    try:
        return Decimal(t)
    except InvalidOperation as exc:  # pragma: no cover - guarded by the regex
        raise Unparseable(field, token, "invalid number") from exc


def fmt(value: Decimal | int | float, places: int = 2) -> str:
    """Render a decimal without trailing zeros, rounded half-even to ``places``."""
    d = Decimal(str(value)).quantize(Decimal(1).scaleb(-places))
    s = format(d.normalize(), "f")
    return s


NUM = r"\d+(?:[.,]\d+)?"


def nd(d: Decimal) -> Decimal:
    """Strip trailing zeros without switching to exponent notation (400, not 4E+2)."""
    return Decimal(format(d.normalize(), "f"))


@dataclass(frozen=True)
class Strength:
    """Amount of each active component per reference quantity.

    ``components_mg`` follows the order of the ingredient list on the label.
    ``per_ml`` is set for liquids (e.g. 5 mL); ``per_unit`` names a solid dose unit.
    """

    components_mg: tuple[Decimal, ...]
    per_ml: Decimal | None = None
    per_unit: str | None = None

    def mg_per_ml(self, index: int = 0) -> Decimal:
        if self.per_ml is None:
            raise ValueError("strength is not a liquid concentration")
        return self.components_mg[index] / self.per_ml

    def canonical(self) -> str:
        parts = " / ".join(f"{fmt(c, 3)} mg" for c in self.components_mg)
        if self.per_ml is not None:
            return f"{parts} per {fmt(self.per_ml, 3)} mL"
        return f"{parts} per {self.per_unit or 'unit'}"

    def same_concentration(self, other: "Strength") -> bool:
        if len(self.components_mg) != len(other.components_mg):
            return False
        if (self.per_ml is None) != (other.per_ml is None):
            return False
        if self.per_ml is None:
            return self.components_mg == other.components_mg
        return all(
            a / self.per_ml == b / other.per_ml
            for a, b in zip(self.components_mg, other.components_mg)
        )


def parse_strength(raw: str) -> Strength:
    """Parse label or prescription strength text.

    Accepted shapes include ``250 mg/5 mL``, ``400 mg/57 mg per 5 mL``, ``400/57 mg/5 mL``,
    ``250 mg + 62.5 mg / 5 mL``, ``0.25 g/5 mL``, ``50 mg/mL`` and ``500 mg tablet``.
    """
    text = clean(raw)
    text = text.replace("milligrams", "mg").replace("milligram", "mg")
    text = re.sub(r"\bmls?\b", "ml", text)
    # Decimal commas ("62,5 mg") become points; "1,000" keeps its comma and is rejected below.
    text = re.sub(r"(\d),(\d{1,2})(?!\d)", r"\1.\2", text)
    if not text:
        raise Unparseable("strength", raw, "empty")
    # Liquid reference volume: "per 5 ml", "/5 ml", "/ ml", "in 5 ml", "pour 5 ml".
    vol = re.search(rf"(?:per|/|in|pour|par)\s*({NUM})?\s*(ml|cc)\b\s*$", text)
    per_ml: Decimal | None = None
    body = text
    if vol:
        per_ml = to_decimal(vol.group(1), "strength") if vol.group(1) else Decimal(1)
        if per_ml == 0:
            raise Unparseable("strength", raw, "zero reference volume")
        body = text[: vol.start()].strip().rstrip("/").strip()
    per_unit = None
    solid = re.search(r"\b(tablets?|tabs?|capsules?|caps?|comprimés?|gélules?|sachets?)\b", body)
    if per_ml is None:
        if solid:
            per_unit = "tablet" if solid.group(1).startswith(("tab", "comp")) else "capsule"
            if solid.group(1).startswith("sachet"):
                per_unit = "sachet"
            body = (body[: solid.start()] + body[solid.end() :]).strip()
        else:
            raise Unparseable("strength", raw, "no reference volume or dose unit")
    # Shared-unit form: "400/57 mg"
    shared = re.fullmatch(rf"({NUM})\s*(?:/|\+)\s*({NUM})\s*(mg|g|mcg|µg|μg|ug)", body)
    comps: list[Decimal] = []
    if shared:
        unit = MASS_TO_MG[shared.group(3)]
        comps = [to_decimal(shared.group(1), "strength") * unit, to_decimal(shared.group(2), "strength") * unit]
    else:
        pieces = [p.strip() for p in re.split(r"\s*(?:\+|/|,|;|\band\b|\bet\b)\s*", body) if p.strip()]
        for piece in pieces:
            m = re.fullmatch(rf"({NUM})\s*(mg|g|gm|mcg|µg|μg|ug)", piece)
            if not m:
                raise Unparseable("strength", raw, f"unrecognised component {piece!r}")
            comps.append(to_decimal(m.group(1), "strength") * MASS_TO_MG[m.group(2)])
    if not comps or len(comps) > 3:
        raise Unparseable("strength", raw, "expected one to three active components")
    if any(c <= 0 for c in comps):
        raise Unparseable("strength", raw, "non-positive component")
    return Strength(tuple(nd(c) for c in comps), nd(per_ml) if per_ml else None, per_unit)


@dataclass(frozen=True)
class Dose:
    """A single administered amount: a volume for liquids or a mass/count for solids."""

    volume_ml: Decimal | None = None
    mass_mg: Decimal | None = None
    units: Decimal | None = None
    unit_name: str | None = None


AMBIGUOUS_MEASURES = re.compile(
    r"\b(spoon|spoonful|tsp|teaspoon|tbsp|tablespoon|cuill[eè]re|capful|cap|dropper|dropperful|pipette|squirt|sip)\b"
)


def parse_dose(raw: str) -> Dose:
    """Parse one administered dose. Household measures and alternatives fail closed."""
    text = clean(raw)
    text = re.sub(r"\bmls?\b", "ml", text)
    if AMBIGUOUS_MEASURES.search(text):
        raise Unparseable("dose", raw, "household measure has no defined volume")
    if re.search(r"\bor\b|\bou\b|\?|-\s*\d|\d\s*-\s*\d|\bto\b", text):
        raise Unparseable("dose", raw, "more than one possible amount")
    vols = re.findall(rf"({NUM})\s*(ml|cc)\b", text)
    masses = re.findall(rf"({NUM})\s*(mg|g|gm|mcg|µg|μg|ug)\b", text)
    units = re.findall(rf"({NUM})\s*(tablets?|tabs?|capsules?|caps?|sachets?|comprimés?|gélules?)\b", text)
    # Every number must belong to an amount, a count or a duration: a stray one is a second candidate amount
    # ("2.5 7.5 ml", an overwritten "2.57.5ml"), never something to drop.
    rest = re.sub(rf"({NUM})\s*(ml|cc|mg|g|gm|mcg|µg|μg|ug|tablets?|tabs?|capsules?|caps?|sachets?|comprimés?|gélules?)\b", " ", text)
    rest = re.sub(rf"\b({NUM})\s*(x|times?|fois|days?|jours?|hours?|hrs?|h|heures?)\b", " ", rest)
    rest = re.sub(r"\bq\s*\d+\s*h\b", " ", rest)
    if re.search(r"\d", rest):
        raise Unparseable("dose", raw, "more than one possible amount")
    if len(vols) == 1 and not units:
        v = to_decimal(vols[0][0], "dose") * VOLUME_TO_ML[vols[0][1]]
        if v <= 0:
            raise Unparseable("dose", raw, "non-positive volume")
        mass = None
        if len(masses) == 1:
            mass = to_decimal(masses[0][0], "dose") * MASS_TO_MG[masses[0][1]]
        return Dose(volume_ml=nd(v), mass_mg=nd(mass) if mass else None)
    if len(vols) > 1:
        raise Unparseable("dose", raw, "more than one volume")
    if len(units) == 1 and not vols:
        return Dose(units=to_decimal(units[0][0], "dose"), unit_name=units[0][1])
    if len(masses) == 1:
        m = to_decimal(masses[0][0], "dose") * MASS_TO_MG[masses[0][1]]
        if m <= 0:
            raise Unparseable("dose", raw, "non-positive mass")
        return Dose(mass_mg=nd(m))
    raise Unparseable("dose", raw, "no single volume, mass or unit count")


@dataclass(frozen=True)
class Frequency:
    per_day: Decimal
    interval_h: Decimal | None
    label: str


_COUNT_WORDS = {"once": 1, "one": 1, "1": 1, "une": 1, "un": 1, "twice": 2, "two": 2, "2": 2, "deux": 2,
                "thrice": 3, "three": 3, "3": 3, "trois": 3, "four": 4, "4": 4, "quatre": 4}
_COUNT = "|".join(sorted(_COUNT_WORDS, key=len, reverse=True))
_FREQ_WORDS: list[tuple[str, int | None]] = [
    # "<count> [times|x|fois] [a|per|par] day/daily/jour": the count word decides
    (rf"\b({_COUNT})\s*(?:times?|x|fois)?\s*(?:a|per|/|par)?\s*(?:day|daily|jour)\b", None),
    (r"\b(od|qd|daily|every day|q24h|every 24 ?h(ours)?|tous les jours)\b", 1),
    (r"\b(bid|bd|b\.i\.d\.?|q12h|every 12 ?h(ours)?)(?=\W|$)", 2),
    (r"\b(tid|tds|t\.i\.d\.?|q8h|every 8 ?h(ours)?)(?=\W|$)", 3),
    (r"\b(qid|qds|q\.i\.d\.?|q6h|every 6 ?h(ours)?)(?=\W|$)", 4),
]


def parse_frequency(raw: str) -> Frequency:
    text = clean(raw)
    if re.search(r"\b(prn|as needed|if needed|si besoin|when required)\b", text):
        raise Unparseable("frequency", raw, "as-needed dosing has no fixed daily count")
    if re.search(r"q\s*\d+\s*-\s*\d+\s*h|every \d+\s*(-|to)\s*\d+", text):
        raise Unparseable("frequency", raw, "interval range admits more than one daily count")
    hits: set[int] = set()
    m = re.search(r"\bq\s*(\d+)\s*h\b|\bevery (\d+) ?h(ours?|rs?)?\b", text)
    if m:
        hours = int(m.group(1) or m.group(2))
        if hours <= 0 or 24 % hours:
            raise Unparseable("frequency", raw, "interval does not divide a day")
        hits.add(24 // hours)
        text = text[: m.start()] + " " + text[m.end() :]
    # Count phrases first; each match is removed so "three times daily" is not also read as "daily".
    for pattern, n in _FREQ_WORDS:
        for mm in list(re.finditer(pattern, text)):
            hits.add(n if n is not None else _COUNT_WORDS[mm.group(1)])
        text = re.sub(pattern, " ", text)
    if len(hits) != 1:
        raise Unparseable("frequency", raw, "no single daily count" if not hits else "conflicting daily counts")
    n = hits.pop()
    return Frequency(per_day=Decimal(n), interval_h=Decimal(24) / Decimal(n), label=f"{n}x/day (every {24 // n} h)")


def parse_duration_days(raw: str) -> Decimal:
    text = clean(raw)
    uk = re.fullmatch(r"(?:x|for)?\s*(\d+)\s*/\s*7", text)
    if uk:
        return Decimal(uk.group(1))
    if re.search(r"\bor\b|\bou\b|\d\s*-\s*\d|\bto\b", text):
        raise Unparseable("duration", raw, "more than one possible duration")
    m = re.search(rf"({NUM})\s*(days?|d|jours?|j)\b", text)
    if m:
        return to_decimal(m.group(1), "duration")
    m = re.search(rf"({NUM})\s*(weeks?|wk|semaines?)\b", text)
    if m:
        return to_decimal(m.group(1), "duration") * 7
    raise Unparseable("duration", raw, "no duration in days or weeks")


def parse_weight_kg(raw: str) -> Decimal:
    text = clean(raw)
    m = re.fullmatch(rf"(?:weight|wt|poids|w)?\s*[:=]?\s*({NUM})\s*(kg|kgs|kilos?|kilograms?)", text)
    if m:
        return nd(to_decimal(m.group(1), "weight"))
    m = re.fullmatch(rf"(?:weight|wt|poids|w)?\s*[:=]?\s*({NUM})\s*(lb|lbs|pounds?)", text)
    if m:
        return (to_decimal(m.group(1), "weight") * LB_TO_KG).quantize(Decimal("0.01"))
    raise Unparseable("weight", raw, "weight needs an explicit kg or lb unit")


def parse_age_months(raw: str) -> Decimal:
    text = clean(raw)
    total = Decimal(0)
    found = False
    for num, unit in re.findall(rf"({NUM})\s*(years?|yrs?|y|ans?|months?|mo|mois|weeks?|wk|semaines?|days?|d|jours?)\b", text):
        v = to_decimal(num, "age")
        if unit.startswith(("y", "an")):
            total += v * 12
        elif unit.startswith(("mo", "mois")):
            total += v
        elif unit.startswith(("w", "sem")):
            total += v * 7 / Decimal("30.4375")
        else:
            total += v / Decimal("30.4375")
        found = True
    if not found:
        raise Unparseable("age", raw, "age needs an explicit unit")
    return total.quantize(Decimal("0.01"))


_MONTHS = {
    m: i + 1
    for i, names in enumerate(
        [
            ("jan", "janv"), ("feb", "fev", "fév"), ("mar", "mars"), ("apr", "avr"), ("may", "mai"), ("jun", "juin"),
            ("jul", "juil"), ("aug", "aou", "aoû"), ("sep", "sept"), ("oct",), ("nov",), ("dec", "déc"),
        ]
    )
    for m in names
}


def parse_expiry(raw: str) -> date:
    """Parse an expiry. Month-only expiries resolve to the last day of that month."""
    text = clean(raw)
    text = re.sub(r"^(exp(iry|iration)?\.?|use by|pér\.?|per\.?|exp date)\s*[:.]?\s*", "", text)
    iso = re.search(r"(20\d\d)[-/.](\d{1,2})(?:[-/.](\d{1,2}))?", text)
    if iso:
        y, mth, d = int(iso.group(1)), int(iso.group(2)), iso.group(3)
        return _mk_date(raw, y, mth, int(d) if d else None)
    my = re.search(r"\b(\d{1,2})[-/.](20\d\d|\d\d)\b", text)
    if my:
        y = int(my.group(2))
        y = y + 2000 if y < 100 else y
        return _mk_date(raw, y, int(my.group(1)), None)
    named = re.search(r"\b([a-zéû]{3,9})\.?\s*(20\d\d)\b", text)
    if named:
        word = named.group(1)
        for key in (word[:4], word[:3]):
            if key in _MONTHS:
                return _mk_date(raw, int(named.group(2)), _MONTHS[key], None)
    raise Unparseable("expiry", raw, "no month and year")


def _mk_date(raw: str, y: int, m: int, d: int | None) -> date:
    import calendar

    if not 1 <= m <= 12:
        raise Unparseable("expiry", raw, "month out of range")
    last = calendar.monthrange(y, m)[1]
    if d is None:
        return date(y, m, last)
    if not 1 <= d <= last:
        raise Unparseable("expiry", raw, "day out of range")
    return date(y, m, d)


def parse_volume_ml(raw: str) -> Decimal:
    text = clean(raw)
    text = re.sub(r"\bmls?\b", "ml", text)
    vols = re.findall(rf"({NUM})\s*(ml|cc|l)\b", text)
    if len(set(vols)) != 1:
        raise Unparseable("volume", raw, "no single volume")
    num, unit = vols[0]
    return nd(to_decimal(num, "volume") * VOLUME_TO_ML[unit])


def parse_lot(raw: str) -> str:
    text = unicodedata.normalize("NFKC", raw or "").strip()
    text = re.sub(r"^(lot|batch|lot no\.?|lot n°|lot number|b/n|bn)\s*[:#.]?\s*", "", text, flags=re.I)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9\-/]{2,19}", text):
        raise Unparseable("lot", raw, "not a lot code")
    return text.upper()


@dataclass
class Calc:
    """One step of a reproducible calculation trace."""

    name: str
    formula: str
    inputs: dict[str, str]
    value: Decimal
    unit: str
    steps: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "formula": self.formula,
            "inputs": self.inputs,
            "value": fmt(self.value, 3),
            "unit": self.unit,
            "steps": self.steps,
        }


_MFR_LEAD = re.compile(r"^\s*(?:manufactured|made|mfd\.?|mfg\.?|distributed|marketed|fabriqu[ée]|distribu[ée])\s*(?:for|by|par|pour)?\s*[:\-]?\s*", re.I)


def manufacturer_name(text: str) -> str:
    """The company name from a label line ("Manufactured by Solway Medicines" -> "Solway Medicines")."""
    return _MFR_LEAD.sub("", text or "").strip().rstrip(",;").strip() or (text or "").strip()
