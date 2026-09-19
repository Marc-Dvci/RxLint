"""Reading-reliability head: a calibrated LightGBM model on top of the generative readers.

For every reading the model makes, the head estimates the probability that the reading is
exactly right, from signals the generative model does not see together: its own confidence,
what an independent OCR reader saw, whether RxLint's grammar can parse the text, whether the
strength exists in marketed products, how sharp the pixels inside the box are, and whether
the model's box agrees with the OCR box.

The head is a second gate on high-risk readings (policy P-PERC-03). A reading still needs OCR
corroboration first (P-PERC-02); a corroborated reading the head scores below threshold goes to
the pharmacist for confirmation as well. The head adds confirmations, never removes one, and
never touches a clinical rule.
"""

from __future__ import annotations

import io
import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np

from ..core.normalize import Normalizer
from ..core.units import (manufacturer_name, Unparseable, parse_age_months, parse_dose, parse_duration_days, parse_expiry, parse_frequency,
                          parse_lot, parse_strength, parse_volume_ml, parse_weight_kg)
from .grounding import CORROBORATION_REQUIRED, _confusable_digits, contains_sequence, numbers

MODEL_DIR = Path(__file__).resolve().parents[3] / "models" / "reliability"
FIELDS = ["rx.drug", "rx.strength", "rx.dose", "rx.frequency", "rx.duration", "rx.indication", "rx.route", "rx.patient_age",
          "rx.patient_weight", "rx.allergies", "dispensed.drug", "dispensed.strength", "dispensed.volume", "dispensed.lot",
          "dispensed.expiry", "dispensed.manufacturer", "dispensed.gtin"]
CORR = ["corroborated", "unconfirmed", "contradicted", "located", "unmatched"]

PARSERS = {
    "rx.strength": parse_strength, "dispensed.strength": parse_strength, "rx.dose": parse_dose, "rx.frequency": parse_frequency,
    "rx.duration": parse_duration_days, "rx.patient_weight": parse_weight_kg, "rx.patient_age": parse_age_months,
    "dispensed.volume": parse_volume_ml, "dispensed.lot": parse_lot, "dispensed.expiry": parse_expiry,
}

FEATURES = (["confidence", "legible", "n_alternatives", "ocr_match", "ocr_score", "numbers_agree", "ocr_confusable",
             "parses", "strength_recognised", "sharpness_ratio", "box_iou", "text_len", "n_digits", "doc_legibility",
             "doc_ocr_mean", "is_prescription"] + [f"corr_{c}" for c in CORR] + [f"field_{f}" for f in FIELDS])


def canonical(field: str, text: str, n: Normalizer | None = None) -> str | None:
    """A comparable canonical form of a reading, or None when it cannot be parsed."""
    t = (text or "").strip()
    if field in PARSERS:
        try:
            v = PARSERS[field](t)
        except Unparseable:
            return None
        return json.dumps(v.__dict__ if hasattr(v, "__dict__") else str(v), default=str, sort_keys=True)
    if field.endswith(".drug") and n is not None:
        r = n.product(t)
        return r.value if r.status == "exact" else None
    if field == "rx.indication" and n is not None:
        return n.indication(t).value
    if field == "dispensed.manufacturer":
        t = manufacturer_name(t).rstrip(".")
    if field == "dispensed.gtin":
        d = re.sub(r"\D", "", t)
        return d or None
    return re.sub(r"\s+", " ", t.lower()) or None


def _iou(a: list[float] | None, b: list[float] | None) -> float:
    if not a or not b:
        return 0.0
    x0, y0, x1, y1 = max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, x1 - x0) * max(0.0, y1 - y0)
    ua = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / ua if ua > 0 else 0.0


class ImageStats:
    """Sharpness of a region relative to the whole page (Laplacian variance)."""

    def __init__(self, image_bytes: bytes):
        import cv2
        from PIL import Image

        img = np.asarray(Image.open(io.BytesIO(image_bytes)).convert("L"))
        self.lap = cv2.Laplacian(img.astype(np.float32), cv2.CV_32F)
        self.h, self.w = img.shape
        self.page = float(self.lap.var()) + 1e-6

    def ratio(self, bbox: list[float] | None) -> float:
        if not bbox:
            return 1.0
        x0, y0, x1, y1 = (int(bbox[0] * self.w), int(bbox[1] * self.h), int(bbox[2] * self.w), int(bbox[3] * self.h))
        if x1 - x0 < 4 or y1 - y0 < 4:
            return 1.0
        return float(self.lap[y0:y1, x0:x1].var()) / self.page


def features(ob: dict[str, Any], kind: str, doc: dict[str, Any], stats: ImageStats | None, n: Normalizer) -> dict[str, float]:
    field = ob["field"]
    text = ob.get("text", "")
    parsed = canonical(field, text, n)
    strength_ok = 0.5
    if field.endswith("strength") and parsed:
        try:
            s = parse_strength(text)
            prods = [p for p in n.recognised_strengths]
            strength_ok = float(any(n.strength_recognised(p, [float(c) for c in s.components_mg], float(s.per_ml) if s.per_ml else None)
                                    for p in prods))
        except Unparseable:
            strength_ok = 0.0
    ocr_text = ob.get("ocr_text") or ""
    f: dict[str, float] = {
        "confidence": float(ob.get("confidence") or 0.5),
        "legible": float(ob.get("legible", True)),
        "n_alternatives": float(len(ob.get("alternatives") or [])),
        "ocr_match": float(ob.get("ocr_match") or 0.0),
        "ocr_score": float(ob.get("ocr_score") or 0.0),
        "numbers_agree": float(contains_sequence(numbers(text), numbers(ocr_text))) if numbers(text) else 0.5,
        "ocr_confusable": float(_confusable_digits(ocr_text)),
        "parses": float(parsed is not None),
        "strength_recognised": strength_ok,
        "sharpness_ratio": float(stats.ratio(ob.get("bbox")) if stats else 1.0),
        "box_iou": _iou(ob.get("model_bbox"), ob.get("bbox") if ob.get("grounding") == "ocr" else None),
        "text_len": float(len(text)),
        "n_digits": float(sum(ch.isdigit() for ch in text)),
        "doc_legibility": {"good": 1.0, "partial": 0.5, "poor": 0.0}.get(doc.get("legibility", "good"), 0.5),
        "doc_ocr_mean": float(doc.get("ocr_mean", 0.0)),
        "is_prescription": float(kind == "prescription"),
    }
    for c in CORR:
        f[f"corr_{c}"] = float(ob.get("corroboration") == c)
    for fl in FIELDS:
        f[f"field_{fl}"] = float(field == fl)
    return f


@lru_cache(maxsize=1)
def load_head() -> tuple[Any, dict[str, Any]] | None:
    meta_p, model_p = MODEL_DIR / "head.json", MODEL_DIR / "head.txt"
    if not (meta_p.exists() and model_p.exists()):
        return None
    import lightgbm as lgb

    return lgb.Booster(model_file=str(model_p)), json.loads(meta_p.read_text(encoding="utf-8"))


def calibrate(raw: np.ndarray, meta: dict[str, Any]) -> np.ndarray:
    xs, ys = np.array(meta["calibration"]["x"]), np.array(meta["calibration"]["y"])
    return np.interp(raw, xs, ys)


def apply(observations: list[dict[str, Any]], kind: str, doc: dict[str, Any], image_bytes: bytes, n: Normalizer) -> list[dict[str, Any]]:
    """Score each reading and set ``requires_confirmation`` for high-risk fields under P-PERC-03.

    The head adds a requirement and never removes one: a high-risk reading still needs OCR corroboration
    (P-PERC-02), and a corroborated reading the head scores below threshold goes to the pharmacist as well."""
    head = load_head()
    if head is None:
        return observations
    booster, meta = head
    stats = ImageStats(image_bytes)
    rows = [features(o, kind, doc, stats, n) for o in observations]
    if not rows:
        return observations
    X = np.array([[r[k] for k in meta["features"]] for r in rows], dtype=np.float32)
    p = calibrate(booster.predict(X), meta)
    t = meta["threshold"]
    for o, pi in zip(observations, p):
        o["p_correct"] = round(float(pi), 4)
        if o["field"] in CORROBORATION_REQUIRED:
            unproven = o.get("corroboration") != "corroborated" or not o.get("legible", True)
            o["requires_confirmation"] = bool(unproven or o.get("requires_confirmation") or pi < t)
            o["gate"] = "P-PERC-03"
    return observations
