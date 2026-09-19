"""Spatial grounding and cross-modal corroboration.

An independent OCR engine reads the same image. Each model observation is located among the
OCR lines by fuzzy text match; a match supplies the evidence box. For numeric fields the digit
sequence must agree between the two readers: a disagreement becomes a competing reading, which
makes the fact ambiguous and the case CANNOT_VERIFY rather than silently trusting either reader.
"""

from __future__ import annotations

import difflib
import io
import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import numpy as np

NUMERIC_FIELDS = {"rx.strength", "rx.dose", "rx.duration", "rx.patient_weight", "dispensed.strength",
                  "dispensed.volume", "dispensed.lot", "dispensed.expiry", "rx.patient_age"}
# Fields whose digits must be corroborated by an independent reader or confirmed by a person (policy P-PERC-02).
CORROBORATION_REQUIRED = {"rx.strength", "rx.dose", "rx.patient_weight", "dispensed.strength"}
# Letters an OCR engine returns in place of handwritten digits. Used only to locate a field, never to read it.
CONFUSABLE = str.maketrans({"s": "5", "S": "5", "z": "2", "Z": "2", "o": "0", "O": "0", "l": "1", "I": "1", "i": "1",
                            "g": "9", "b": "6", "B": "8", "a": "2", "q": "9", "t": "7", "T": "7"})
OCR_TRUST = 0.90  # OCR line confidence needed before a digit disagreement counts as a contradiction


@dataclass
class OcrLine:
    text: str
    bbox: list[float]  # normalised
    score: float


@lru_cache(maxsize=1)
def _engine():
    from rapidocr_onnxruntime import RapidOCR

    return RapidOCR()


def ocr_lines(image_bytes: bytes) -> list[OcrLine]:
    from PIL import Image

    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    W, H = img.size
    result, _ = _engine()(np.asarray(img)[:, :, ::-1])
    lines = []
    for pts, text, score in result or []:
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        lines.append(OcrLine(text=text, bbox=[min(xs) / W, min(ys) / H, max(xs) / W, max(ys) / H], score=float(score)))
    return lines


def _key(s: str) -> str:
    return re.sub(r"[^0-9a-z.]", "", s.lower().replace(",", "."))


def _locate_key(s: str) -> str:
    """Key for finding a field on the page: digit look-alikes next to digits or decimal points fold to digits."""
    t = re.sub(r"(?<=[0-9.])[szolIigbBaqtT]|[szolIigbBaqtT](?=[0-9.])", lambda m: m.group(0).translate(CONFUSABLE), s)
    return _key(t)


def _confusable_digits(s: str) -> bool:
    return bool(re.search(r"(?<=[0-9.,])[szolIigbBaqtT]|[szolIigbBaqtT](?=[.,]?[0-9])", s))


def _digits(s: str) -> str:
    return re.sub(r"[^0-9]", "", s)


def numbers(s: str) -> list[str]:
    """Whole numbers in reading order, decimal commas folded: '62,5 mg / 5 mL' -> ['62.5', '5']."""
    return [n.replace(",", ".") for n in re.findall(r"(?<![0-9.,])\d+(?:[.,]\d+)?", s)]


def contains_sequence(needle: list[str], hay: list[str]) -> bool:
    if not needle:
        return False
    return any(hay[i:i + len(needle)] == needle for i in range(len(hay) - len(needle) + 1))


def _union(boxes: list[list[float]]) -> list[float]:
    return [min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes)]


def match(text: str, lines: list[OcrLine]) -> tuple[float, list[OcrLine], str]:
    """Best match of ``text`` against single OCR lines and adjacent pairs; returns (ratio, lines, joined text)."""
    target = _locate_key(text)
    if not target:
        return 0.0, [], ""
    best: tuple[float, list[OcrLine], str] = (0.0, [], "")
    candidates: list[list[OcrLine]] = [[ln] for ln in lines]
    ordered = sorted(lines, key=lambda l: (round(l.bbox[1], 2), l.bbox[0]))
    candidates += [[a, b] for a, b in zip(ordered, ordered[1:])]
    for group in candidates:
        joined = " ".join(l.text for l in group)
        k = _locate_key(joined)
        if not k:
            continue
        if target in k:
            # substring: the observed field is part of a longer OCR line
            ratio = 0.9 + 0.1 * len(target) / len(k)
            span = joined
        else:
            sm = difflib.SequenceMatcher(None, target, k)
            ratio = sm.ratio()
            span = joined
        if ratio > best[0]:
            best = (ratio, group, span)
    return best


def ground(observations: list[dict[str, Any]], lines: list[OcrLine]) -> list[dict[str, Any]]:
    """Attach OCR boxes and corroboration status to model observations (dicts with field/text/...)."""
    out = []
    for ob in observations:
        ob = dict(ob)
        ratio, group, span = match(ob["text"], lines)
        ob["ocr_match"] = round(ratio, 3)
        ob["ocr_text"] = span or None
        if ratio >= 0.72 and group:
            ob["bbox"] = _union([g.bbox for g in group])
            ob["grounding"] = "ocr"
            score = min(g.score for g in group)
            if ob["field"] in NUMERIC_FIELDS:
                n_model, n_ocr = numbers(ob["text"]), numbers(span)
                if contains_sequence(n_model, n_ocr) and score >= OCR_TRUST and not _confusable_digits(span):
                    ob["corroboration"] = "corroborated"
                elif score < OCR_TRUST or _confusable_digits(span) or not n_ocr:
                    ob["corroboration"] = "unconfirmed"  # the second reader could not read the digits
                else:
                    ob["alternatives"] = list(dict.fromkeys([*ob.get("alternatives", []), span]))
                    ob["corroboration"] = "contradicted"
            else:
                ob["corroboration"] = "located"
        else:
            ob["grounding"] = "model" if ob.get("bbox") else None
            ob["corroboration"] = "unmatched"
        ob["requires_confirmation"] = ob["field"] in CORROBORATION_REQUIRED and ob["corroboration"] != "corroborated"
        out.append(ob)
    return out
