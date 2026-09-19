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
CORROBORATION_REQUIRED = {"rx.strength", "rx.dose", "rx.patient_weight", "dispensed.strength", "dispensed.expiry", "dispensed.volume"}
# Letters an OCR engine returns in place of handwritten digits. Used only to locate a field, never to read it.
CONFUSABLE = str.maketrans({"s": "5", "S": "5", "z": "2", "Z": "2", "o": "0", "O": "0", "l": "1", "I": "1", "i": "1",
                            "g": "9", "b": "6", "B": "8", "a": "2", "q": "9", "t": "7", "T": "7"})
OCR_TRUST = 0.90  # OCR line confidence needed before a digit disagreement counts as a contradiction
REREAD_TRUST = 0.85  # a close re-read must also reproduce the exact number sequence


@dataclass
class OcrLine:
    text: str
    bbox: list[float]  # normalised
    score: float


@lru_cache(maxsize=1)
def _engine():
    from rapidocr_onnxruntime import RapidOCR

    # Lower detection thresholds and a larger working size keep small label lines on a bottle photo.
    return RapidOCR(det_limit_side_len=1280, det_box_thresh=0.3, det_thresh=0.2)


def _read(img) -> list[OcrLine]:
    W, H = img.size
    result, _ = _engine()(np.asarray(img)[:, :, ::-1])
    lines = []
    for pts, text, score in result or []:
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        lines.append(OcrLine(text=text, bbox=[min(xs) / W, min(ys) / H, max(xs) / W, max(ys) / H], score=float(score)))
    return lines


def ocr_lines(image_bytes: bytes) -> list[OcrLine]:
    """Read every text line. When the text occupies a small part of the photo (a label on a bottle),
    a second pass re-reads the text region cropped and upscaled, where small lines are legible."""
    from PIL import Image

    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    W, H = img.size
    first = _read(img)
    if not first:
        return first
    x0, y0 = min(l.bbox[0] for l in first), min(l.bbox[1] for l in first)
    x1, y1 = max(l.bbox[2] for l in first), max(l.bbox[3] for l in first)
    pad_x, pad_y = (x1 - x0) * 0.12 + 0.02, (y1 - y0) * 0.12 + 0.02
    x0, y0, x1, y1 = max(0.0, x0 - pad_x), max(0.0, y0 - pad_y), min(1.0, x1 + pad_x), min(1.0, y1 + pad_y)
    crop_px = ((x1 - x0) * W, (y1 - y0) * H)
    if max(crop_px) >= 1400 and (x1 - x0) * (y1 - y0) > 0.5:
        return first  # the text is already large enough
    scale = 1600 / max(crop_px)
    crop = img.crop((int(x0 * W), int(y0 * H), int(x1 * W), int(y1 * H)))
    crop = crop.resize((max(1, int(crop.width * scale)), max(1, int(crop.height * scale))), Image.LANCZOS)
    second = _read(crop)
    if len(second) < len(first):
        return first
    cw, ch = x1 - x0, y1 - y0
    return [OcrLine(text=l.text, score=l.score, bbox=[x0 + l.bbox[0] * cw, y0 + l.bbox[1] * ch, x0 + l.bbox[2] * cw, y0 + l.bbox[3] * ch])
            for l in second]


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


def match(text: str, lines: list[OcrLine], claimed: dict | None = None) -> tuple[float, list[OcrLine], str]:
    """Best match of ``text`` against single OCR lines and adjacent pairs; returns (ratio, lines, joined text).

    Lines already claimed by another field lose a small margin, so a short reading such as "5 mL" that
    appears on two lines is placed on the line no other field explains."""
    claimed = claimed or {}
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
        gkey = tuple(id(g) for g in group)
        taken = claimed.get(gkey, [])
        wholly = any(claimed.get((id(g),)) == [(0, -1)] for g in group)
        if target in k:
            # substring: the observed field is part of a longer OCR line. It overlaps an earlier field
            # only if every occurrence falls inside a span that field already explains.
            ratio = 0.9 + 0.1 * len(target) / len(k)
            starts = [m.start() for m in re.finditer(re.escape(target), k)]
            free = [s for s in starts if not any(s < e and s + len(target) > b for b, e in taken if e >= 0)]
            if wholly or not free:
                ratio -= 0.05
        else:
            ratio = difflib.SequenceMatcher(None, target, k).ratio()
            if taken or wholly:
                ratio -= 0.05
        if ratio > best[0]:
            best = (ratio, group, joined)
    return best


def _claim(claimed: dict[tuple, list[tuple[int, int]]], group: list[OcrLine], target: str) -> None:
    gkey = tuple(id(g) for g in group)
    k = _locate_key(" ".join(l.text for l in group))
    taken = claimed.setdefault(gkey, [])
    for m in re.finditer(re.escape(target), k) if target else []:
        s, e = m.start(), m.end()
        if not any(s < te and e > ts for ts, te in taken if te >= 0):
            taken.append((s, e))
            return
    # A fuzzy match explains the whole line.
    for g in group:
        claimed[(id(g),)] = [(0, -1)]


def reread(image_bytes: bytes, bbox: list[float]) -> list[OcrLine]:
    """Read one region again, cropped with a margin and upscaled so a line is about 64 px tall."""
    from PIL import Image

    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    W, H = img.size
    x0, y0, x1, y1 = bbox
    px, py = (x1 - x0) * 0.08 + 0.01, (y1 - y0) * 0.6 + 0.005
    box = (int(max(0, x0 - px) * W), int(max(0, y0 - py) * H), int(min(1, x1 + px) * W), int(min(1, y1 + py) * H))
    crop = img.crop(box)
    if crop.height < 4 or crop.width < 4:
        return []
    scale = max(1.0, 160 / crop.height)
    crop = crop.resize((int(crop.width * scale), int(crop.height * scale)), Image.LANCZOS)
    return _rows(_read(crop))


def _rows(lines: list[OcrLine]) -> list[OcrLine]:
    """Join fragments that sit on the same text row, left to right; the row keeps its lowest score."""
    rows: list[list[OcrLine]] = []
    for l in sorted(lines, key=lambda l: (l.bbox[1] + l.bbox[3]) / 2):
        cy, h = (l.bbox[1] + l.bbox[3]) / 2, l.bbox[3] - l.bbox[1]
        for row in rows:
            r = row[0]
            if abs((r.bbox[1] + r.bbox[3]) / 2 - cy) < 0.5 * max(h, r.bbox[3] - r.bbox[1]):
                row.append(l)
                break
        else:
            rows.append([l])
    out = []
    for row in rows:
        row.sort(key=lambda l: l.bbox[0])
        out.append(OcrLine(text=" ".join(l.text.strip() for l in row), score=min(l.score for l in row), bbox=_union([l.bbox for l in row])))
    return out


def ground(observations: list[dict[str, Any]], lines: list[OcrLine], image: bytes | None = None) -> list[dict[str, Any]]:
    """Attach OCR boxes and corroboration status to model observations (dicts with field/text/...).

    With the image available, a numeric reading the OCR pass contradicts or could not confirm is read
    again from a close crop. The re-read corroborates only when it contains exactly the model's number
    sequence at OCR confidence; any other re-read leaves the first verdict in place."""
    out: list[dict[str, Any]] = [dict(o) for o in observations]
    claimed: dict[tuple, list[tuple[int, int]]] = {}
    # Longer, more specific readings are placed first.
    for ob in sorted(out, key=lambda o: -len(_locate_key(o.get("text", "")))):
        ob["model_bbox"] = ob.get("bbox")
        ratio, group, span = match(ob["text"], lines, claimed)
        if ratio >= 0.72 and group:
            _claim(claimed, group, _locate_key(ob["text"]))
        ob["ocr_match"] = round(ratio, 3)
        ob["ocr_text"] = span or None
        if ratio >= 0.72 and group:
            ob["bbox"] = _union([g.bbox for g in group])
            ob["grounding"] = "ocr"
            score = min(g.score for g in group)
            ob["ocr_score"] = round(score, 4)
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
        ob["_group"] = tuple(id(g) for g in group) if ratio >= 0.72 and group else None
    # An OCR span that two different readings matched corroborates only the reading that explains it fully:
    # a short reading ("5 mL") inside another field's text ("200 mg per 5 mL") gets no corroboration from it.
    for ob in out:
        if ob["corroboration"] != "corroborated" or ob["_group"] is None:
            continue
        mine = _locate_key(ob["text"])
        for other in out:
            if other is ob or other["_group"] != ob["_group"] or other["field"] == ob["field"]:
                continue
            theirs = _locate_key(other["text"])
            if mine in theirs and len(theirs) > len(mine):
                ob["corroboration"] = "unconfirmed"
                ob["shared_span_with"] = other["field"]
    if image is not None:
        for ob in out:
            if ob["field"] in CORROBORATION_REQUIRED and ob["corroboration"] in ("contradicted", "unconfirmed") and ob.get("bbox") \
                    and ob.get("grounding") == "ocr" and not ob.get("shared_span_with"):
                again = reread(image, ob["bbox"])
                n_model = numbers(ob["text"])
                hit = next((l for l in again if l.score >= REREAD_TRUST and contains_sequence(n_model, numbers(l.text))
                            and not _confusable_digits(l.text)), None)
                if hit is not None:
                    ob["first_ocr_text"] = ob["ocr_text"]
                    ob["ocr_text"] = hit.text
                    ob["corroboration"] = "corroborated"
                    ob["grounding"] = "ocr-reread"
                    ob["alternatives"] = [a for a in ob.get("alternatives", []) if a != ob["first_ocr_text"]]
    for ob in out:
        ob.pop("_group", None)
        ob["requires_confirmation"] = ob["field"] in CORROBORATION_REQUIRED and ob["corroboration"] != "corroborated"
    return out
