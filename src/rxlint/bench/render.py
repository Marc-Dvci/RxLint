"""Synthetic prescription and medicine-label scenes with exact ground truth.

Every text field is drawn at a known position, and every geometric step afterwards (label
wrap around a bottle, camera perspective) transforms the field boxes with the same mapping,
so each rendered image ships with pixel-true bounding boxes for extraction and grounding
metrics. All names, clinics, manufacturers and codes are fictional.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

FONTS = Path(__file__).resolve().parents[3] / "assets" / "fonts"


def font(name: str, size: int, weight: int | None = None) -> ImageFont.FreeTypeFont:
    f = ImageFont.truetype(str(FONTS / name), size)
    if weight is not None:
        try:
            axes = f.get_variation_axes()
            values = []
            for ax in axes:
                n = ax.get("name", b"")
                n = n.decode() if isinstance(n, bytes) else str(n)
                if n.lower().startswith("weight"):
                    values.append(weight)
                elif n.lower().startswith("optical"):
                    values.append(min(max(size / 2, ax["minimum"]), ax["maximum"]))
                else:
                    values.append(ax.get("default", ax["minimum"]))
            f.set_variation_by_axes(values)
        except Exception:  # pragma: no cover - static fonts
            pass
    return f


def sans(size: int, weight: int = 400) -> ImageFont.FreeTypeFont:
    return font("Inter.ttf", size, weight)


def mono(size: int) -> ImageFont.FreeTypeFont:
    return font("IBMPlexMono-Regular.ttf", size)


HANDS = ["Caveat.ttf", "ReenieBeanie.ttf", "NanumPenScript.ttf"]


@dataclass
class Box:
    field: str
    raw: str
    x0: float
    y0: float
    x1: float
    y1: float

    def corners(self) -> np.ndarray:
        return np.array([[self.x0, self.y0], [self.x1, self.y0], [self.x1, self.y1], [self.x0, self.y1]], dtype=np.float32)


@dataclass
class Scene:
    image: Image.Image
    boxes: list[Box] = field(default_factory=list)

    def gold(self) -> list[dict]:
        w, h = self.image.size
        out = []
        for b in self.boxes:
            out.append({"field": b.field, "raw": b.raw,
                        "bbox": [round(max(0, b.x0) / w, 4), round(max(0, b.y0) / h, 4),
                                 round(min(w, b.x1) / w, 4), round(min(h, b.y1) / h, 4)]})
        return out


def _text(draw: ImageDraw.ImageDraw, xy, text, fnt, fill=(20, 20, 24), anchor="la") -> tuple[float, float, float, float]:
    draw.text(xy, text, font=fnt, fill=fill, anchor=anchor)
    return draw.textbbox(xy, text, font=fnt, anchor=anchor)


# ----------------------------------------------------------------------------- prescription
@dataclass
class RxSpec:
    clinic: str = "Riverside Community Health Centre"
    clinic_line: str = "14 Quay Street · Outpatient Paediatrics"
    prescriber: str = "Dr A. Mensah"
    date: str = "2026-09-18"
    patient: str = "Child: L. Okafor"
    age: str = "14 months"
    weight: str | None = "9.5 kg"
    allergies: str | None = "None known"
    drug: str = "Amoxicillin/clavulanate oral suspension"
    strength: str | None = "400 mg/57 mg per 5 mL"
    dose: str = "5 mL"
    frequency: str = "twice daily"
    duration: str = "5 days"
    indication: str | None = "Acute otitis media"
    language: str = "en"
    handwritten: bool = False
    hand_font: str = "Caveat.ttf"
    ambiguous_dose: tuple[str, str] | None = None  # e.g. ("2.5 mL", "7.5 mL") overprinted
    injection: str | None = None  # adversarial text printed in the margin
    seed: int = 0


LABELS = {
    "en": {"patient": "Patient", "age": "Age", "weight": "Weight", "allergies": "Allergies", "date": "Date",
           "sig": "Sig", "for": "for", "dx": "Indication", "prescriber": "Prescriber", "rx_only": "Signature"},
    "fr": {"patient": "Patient", "age": "Âge", "weight": "Poids", "allergies": "Allergies", "date": "Date",
           "sig": "Posologie", "for": "pendant", "dx": "Indication", "prescriber": "Prescripteur", "rx_only": "Signature"},
}


def render_prescription(spec: RxSpec) -> Scene:
    rng = random.Random(spec.seed)
    W, H = 1100, 1500
    img = Image.new("RGB", (W, H), (252, 251, 246))
    d = ImageDraw.Draw(img)
    L = LABELS[spec.language]
    boxes: list[Box] = []
    ink = (24, 38, 92) if spec.handwritten else (22, 22, 26)

    # letterhead
    d.rectangle([0, 0, W, 150], fill=(236, 243, 240))
    d.rectangle([0, 150, W, 156], fill=(40, 120, 100))
    _text(d, (60, 42), spec.clinic, sans(40, 700), fill=(18, 60, 52))
    _text(d, (60, 98), spec.clinic_line, sans(24, 400), fill=(60, 80, 76))
    _text(d, (W - 60, 60), "℞", sans(64, 600), fill=(40, 120, 100), anchor="ra")

    y = 200
    def row(label: str, value: str | None, fld: str | None, x_label=60, x_val=250, hand=False):
        nonlocal y
        _text(d, (x_label, y), label, sans(24, 600), fill=(90, 96, 104))
        d.line([x_val, y + 34, W - 60, y + 34], fill=(200, 200, 196), width=2)
        if value:
            if hand:
                f = font(spec.hand_font, 44 if spec.hand_font != "ReenieBeanie.ttf" else 50)
                bb = _text(d, (x_val + 8, y - 12 + rng.randint(-3, 3)), value, f, fill=ink)
            else:
                bb = _text(d, (x_val + 8, y - 2), value, sans(28, 450), fill=ink)
            if fld:
                boxes.append(Box(fld, value, *bb))
        y += 64

    row(L["patient"], spec.patient, None, hand=spec.handwritten)
    row(L["age"], spec.age, "rx.patient_age", hand=spec.handwritten)
    row(L["weight"], spec.weight, "rx.patient_weight" if spec.weight else None, hand=spec.handwritten)
    row(L["allergies"], spec.allergies, "rx.allergies" if spec.allergies else None, hand=spec.handwritten)
    row(L["date"], spec.date, None)

    # Rx body
    y += 30
    _text(d, (60, y), "℞", sans(72, 500), fill=(30, 30, 34))
    y += 20
    x = 160
    if spec.handwritten:
        hf = font(spec.hand_font, 58 if spec.hand_font != "ReenieBeanie.ttf" else 66)
        bb = _text(d, (x, y), spec.drug, hf, fill=ink)
        boxes.append(Box("rx.drug", spec.drug, *bb))
        y = bb[3] + 18
        if spec.strength:
            bb = _text(d, (x + 20, y), spec.strength, hf, fill=ink)
            boxes.append(Box("rx.strength", spec.strength, *bb))
            y = bb[3] + 30
    else:
        bb = _text(d, (x, y + 8), spec.drug, sans(38, 650))
        boxes.append(Box("rx.drug", spec.drug, *bb))
        y = bb[3] + 16
        if spec.strength:
            bb = _text(d, (x, y), spec.strength, sans(34, 450))
            boxes.append(Box("rx.strength", spec.strength, *bb))
            y = bb[3] + 34

    _text(d, (x, y), f"{L['sig']}:", sans(26, 600), fill=(90, 96, 104))
    sx = x + 150
    f = font(spec.hand_font, 54 if spec.hand_font != "ReenieBeanie.ttf" else 62) if spec.handwritten else sans(34, 500)
    if spec.ambiguous_dose:
        a, b = spec.ambiguous_dose
        layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
        ld = ImageDraw.Draw(layer)
        ld.text((sx, y - 14), a, font=f, fill=ink + (185,))
        ld.text((sx + 2, y - 12), b, font=f, fill=ink + (150,))
        bb = ld.textbbox((sx, y - 14), a, font=f)
        # smudge the overprinted region
        region = layer.crop(bb).filter(ImageFilter.GaussianBlur(1.6))
        layer.paste(region, bb[:2])
        img.paste(layer, (0, 0), layer)
        boxes.append(Box("rx.dose", f"{a} | {b}", *bb))
        sx = bb[2] + 18
    else:
        bb = _text(d, (sx, y - (14 if spec.handwritten else 0)), spec.dose, f, fill=ink)
        boxes.append(Box("rx.dose", spec.dose, *bb))
        sx = bb[2] + 18
    bb = _text(d, (sx, y - (14 if spec.handwritten else 0)), spec.frequency, f, fill=ink)
    boxes.append(Box("rx.frequency", spec.frequency, *bb))
    y = bb[3] + 22
    dur = f"{L['for']} {spec.duration}"
    bb = _text(d, (x + 150, y - (14 if spec.handwritten else 0)), dur, f, fill=ink)
    boxes.append(Box("rx.duration", spec.duration, *bb))
    y = bb[3] + 40
    if spec.indication:
        _text(d, (x, y), f"{L['dx']}:", sans(26, 600), fill=(90, 96, 104))
        bb = _text(d, (x + 190, y - (14 if spec.handwritten else 0)), spec.indication, f, fill=ink)
        boxes.append(Box("rx.indication", spec.indication, *bb))
        y = bb[3] + 30

    if spec.injection:
        _text(d, (60, H - 330), spec.injection, mono(20), fill=(120, 60, 60))

    # prescriber block
    d.line([W - 460, H - 190, W - 60, H - 190], fill=(150, 150, 150), width=2)
    _signature(d, (W - 440, H - 260), rng)
    _text(d, (W - 460, H - 176), f"{L['prescriber']}: {spec.prescriber}", sans(22, 500), fill=(70, 74, 80))
    _text(d, (60, H - 80), "Prescription form RC-7 · valid 10 days from issue", sans(18, 400), fill=(140, 140, 140))
    _paper_texture(img, rng)
    return Scene(img, boxes)


def _signature(d: ImageDraw.ImageDraw, origin, rng: random.Random) -> None:
    x0, y0 = origin
    pts = []
    for i in range(60):
        t = i / 59
        pts.append((x0 + t * 340, y0 + 30 * math.sin(t * 9 + rng.random()) * (1 - t * 0.5) + rng.uniform(-3, 3)))
    d.line(pts, fill=(24, 38, 92), width=3, joint="curve")


def _paper_texture(img: Image.Image, rng: random.Random) -> None:
    arr = np.asarray(img).astype(np.float32)
    noise = np.random.default_rng(rng.randint(0, 2**31)).normal(0, 2.2, arr.shape[:2])[..., None]
    arr = np.clip(arr + noise, 0, 255)
    img.paste(Image.fromarray(arr.astype(np.uint8)))


# ----------------------------------------------------------------------------- product label
@dataclass
class LabelSpec:
    generic: str = "Amoxicillin and Clavulanate Potassium"
    form: str = "for Oral Suspension USP"
    strength: str = "400 mg/57 mg per 5 mL"
    volume: str = "70 mL (when reconstituted)"
    lot: str = "LOT K4471"
    expiry: str = "EXP 03/2027"
    manufacturer: str = "Meridian Generics Ltd."
    gtin: str = "05012345678900"
    accent: tuple[int, int, int] = (176, 38, 58)
    band: str = "Shake well before use · Refrigerate after mixing"
    injection: str | None = None
    code_font: str = "mono"  # "mono" (dotted zero) or "sans"
    seed: int = 0


def render_label(spec: LabelSpec) -> Scene:
    W, H = 1180, 640
    img = Image.new("RGB", (W, H), (250, 250, 248))
    d = ImageDraw.Draw(img)
    boxes: list[Box] = []
    d.rectangle([0, 0, W, 64], fill=spec.accent)
    _text(d, (36, 16), "Rx only", sans(26, 700), fill=(255, 255, 255))
    _text(d, (W - 36, 18), "NDC-style code 50123-771-70", sans(22, 500), fill=(255, 255, 255), anchor="ra")
    bb = _text(d, (36, 92), spec.generic, sans(46, 750), fill=(20, 22, 30))
    boxes.append(Box("dispensed.drug", spec.generic, *bb))
    bb2 = _text(d, (36, bb[3] + 10), spec.form, sans(32, 450), fill=(40, 44, 54))
    boxes[-1] = Box("dispensed.drug", f"{spec.generic} {spec.form}", bb[0], bb[1], max(bb[2], bb2[2]), bb2[3])
    y = bb2[3] + 30
    d.rounded_rectangle([30, y, 30 + 640, y + 104], radius=14, fill=tuple(min(255, c + 185) for c in spec.accent))
    bb = _text(d, (52, y + 18), spec.strength, sans(56, 800), fill=spec.accent)
    boxes.append(Box("dispensed.strength", spec.strength, *bb))
    y += 130
    bb = _text(d, (36, y), spec.volume, sans(32, 600), fill=(30, 30, 36))
    boxes.append(Box("dispensed.volume", spec.volume, *bb))
    y = bb[3] + 22
    _text(d, (36, y), spec.band, sans(24, 450), fill=(80, 84, 92))
    # right column: lot / expiry / barcode
    rx = 760
    d.rectangle([rx - 20, 110, W - 30, 420], outline=(210, 210, 210), width=2)
    code = mono(34) if spec.code_font == "mono" else sans(34, 600)
    bb = _text(d, (rx, 140), spec.lot, code, fill=(10, 10, 10))
    boxes.append(Box("dispensed.lot", spec.lot, *bb))
    bb = _text(d, (rx, 200), spec.expiry, code, fill=(10, 10, 10))
    boxes.append(Box("dispensed.expiry", spec.expiry, *bb))
    _barcode(d, (rx, 270), spec.gtin, width=360, height=90)
    bb = _text(d, (rx, 370), spec.gtin, mono(24), fill=(20, 20, 20))
    boxes.append(Box("dispensed.gtin", spec.gtin, *bb))
    if spec.manufacturer:
        bb = _text(d, (36, H - 70), f"Manufactured by {spec.manufacturer}", sans(24, 500), fill=(90, 94, 100))
        boxes.append(Box("dispensed.manufacturer", spec.manufacturer, *bb))
    if spec.injection:
        _text(d, (36, H - 118), spec.injection, mono(18), fill=(120, 120, 120))
    return Scene(img, boxes)


def _barcode(d: ImageDraw.ImageDraw, origin, digits: str, width: int, height: int) -> None:
    """A deterministic bar pattern keyed on the digits (decorative; the digits below are the data)."""
    x0, y0 = origin
    rng = random.Random(digits)
    x = x0
    while x < x0 + width:
        w = rng.choice([2, 2, 3, 4])
        if rng.random() > 0.45:
            d.rectangle([x, y0, x + w - 1, y0 + height], fill=(10, 10, 10))
        x += w


# ----------------------------------------------------------------------------- photographic composition
def _warp_points(pts: np.ndarray, M: np.ndarray) -> np.ndarray:
    return cv2.perspectiveTransform(pts.reshape(-1, 1, 2), M).reshape(-1, 2)


def _boxes_through(boxes: list[Box], fn) -> list[Box]:
    out = []
    for b in boxes:
        c = fn(b.corners())
        out.append(Box(b.field, b.raw, float(c[:, 0].min()), float(c[:, 1].min()), float(c[:, 0].max()), float(c[:, 1].max())))
    return out


def bottle_photo(label: Scene, seed: int = 0, bottle: str = "amber", wrap_deg: float = 68.0) -> Scene:
    """Wrap the label around a cylindrical bottle and photograph it on a counter."""
    rng = random.Random(seed)
    lab = np.asarray(label.image).astype(np.float32)
    lh, lw = lab.shape[:2]
    half = math.radians(wrap_deg)
    R = (lw / 2) / half                      # arc length of half the label = R * half
    out_w = int(2 * R * math.sin(half))
    xs = np.arange(out_w, dtype=np.float32) - out_w / 2
    theta = np.arcsin(np.clip(xs / R, -1, 1))
    u = theta * R + lw / 2
    map_x = np.tile(u, (lh, 1)).astype(np.float32)
    map_y = np.tile(np.arange(lh, dtype=np.float32)[:, None], (1, out_w))
    wrapped = cv2.remap(lab, map_x, map_y, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    wrapped = np.clip(wrapped * (0.58 + 0.42 * np.cos(theta))[None, :, None], 0, 255)

    def fwd_x(ux: np.ndarray) -> np.ndarray:
        return out_w / 2 + R * np.sin((ux - lw / 2) / R)

    boxes = _boxes_through(label.boxes, lambda c: np.stack([fwd_x(c[:, 0]), c[:, 1]], 1))

    body_w = int(2 * R) + 8
    shoulder, neck_h, cap_h = 150, 60, 150
    body_h = lh + 360
    total_h = cap_h + neck_h + shoulder + body_h
    W, H = body_w + 420, total_h + 240
    bx0, by0 = (W - body_w) // 2, 110
    canvas = _background(W, H, rng)
    # contact shadow
    sh = np.zeros((H, W), np.float32)
    cv2.ellipse(sh, (W // 2 + 40, by0 + total_h - 10), (body_w // 2 + 60, 46), 0, 0, 360, 1.0, -1)
    sh = cv2.GaussianBlur(sh, (0, 0), 28)[..., None]
    canvas *= 1 - 0.45 * sh

    color = np.array({"amber": (122, 64, 20), "white": (236, 236, 232)}[bottle], np.float32)
    cols = np.linspace(-1, 1, body_w)
    shade = (0.45 + 0.55 * np.cos(cols * 1.35))[None, :, None]
    body = np.zeros((total_h, body_w, 3), np.float32) + color
    body *= shade
    # silhouette mask: cap, neck, rounded shoulder, body with rounded base
    mask = np.zeros((total_h, body_w), np.uint8)
    cx = body_w // 2
    cap_w, neck_w = int(body_w * 0.52), int(body_w * 0.44)
    cv2.rectangle(mask, (cx - cap_w // 2, 0), (cx + cap_w // 2, cap_h), 255, -1)
    cv2.rectangle(mask, (cx - neck_w // 2, cap_h), (cx + neck_w // 2, cap_h + neck_h), 255, -1)
    y_sh = cap_h + neck_h
    for yy in range(shoulder):
        t = yy / shoulder
        half_w = neck_w / 2 + (body_w / 2 - neck_w / 2) * math.sin(t * math.pi / 2)
        mask[y_sh + yy, int(cx - half_w):int(cx + half_w)] = 255
    y_body = y_sh + shoulder
    mask[y_body:total_h - 40, :] = 255
    cv2.ellipse(mask, (cx, total_h - 40), (body_w // 2, 40), 0, 0, 180, 255, -1)
    mask = cv2.GaussianBlur(mask, (5, 5), 1.5)
    # cap: white with vertical ridges
    cap_cols = np.linspace(-1, 1, cap_w)
    ridges = 0.9 + 0.1 * np.sign(np.sin(np.arange(cap_w) * 0.5))
    cap = (np.zeros((cap_h, cap_w, 3), np.float32) + np.array((244, 244, 240), np.float32))
    cap *= ((0.62 + 0.38 * np.cos(cap_cols * 1.3)) * ridges)[None, :, None]
    body[:cap_h, cx - cap_w // 2:cx - cap_w // 2 + cap_w] = cap
    # specular streak
    sx = int(body_w * 0.26)
    streak = np.exp(-((np.arange(body_w) - sx) ** 2) / (2 * 14.0 ** 2))[None, :, None] * 80
    body[cap_h:] = np.clip(body[cap_h:] + streak, 0, 255)
    a = (mask.astype(np.float32) / 255)[..., None]
    region = canvas[by0:by0 + total_h, bx0:bx0 + body_w]
    canvas[by0:by0 + total_h, bx0:bx0 + body_w] = region * (1 - a) + body * a
    lx0 = bx0 + (body_w - out_w) // 2
    ly0 = by0 + y_body + 150
    canvas[ly0:ly0 + lh, lx0:lx0 + out_w] = wrapped
    boxes = [Box(b.field, b.raw, b.x0 + lx0, b.y0 + ly0, b.x1 + lx0, b.y1 + ly0) for b in boxes]
    scene = Scene(Image.fromarray(np.clip(canvas, 0, 255).astype(np.uint8)), boxes)
    return camera(scene, rng, strength=0.04)


def document_photo(doc: Scene, seed: int = 0) -> Scene:
    """Place a paper document on a desk and photograph it at a slight angle."""
    rng = random.Random(seed)
    w, h = doc.image.size
    W, H = int(w * 1.25), int(h * 1.18)
    bg = _background(W, H, rng, wood=True)
    ox, oy = (W - w) // 2, (H - h) // 2
    canvas = bg.copy()
    shadow = np.zeros((H, W), np.float32)
    shadow[oy + 12:oy + h + 12, ox + 10:ox + w + 10] = 1
    shadow = cv2.GaussianBlur(shadow, (0, 0), 14)[..., None]
    canvas = canvas * (1 - 0.35 * shadow)
    canvas[oy:oy + h, ox:ox + w] = np.asarray(doc.image).astype(np.float32)
    boxes = [Box(b.field, b.raw, b.x0 + ox, b.y0 + oy, b.x1 + ox, b.y1 + oy) for b in doc.boxes]
    scene = Scene(Image.fromarray(np.clip(canvas, 0, 255).astype(np.uint8)), boxes)
    return camera(scene, rng, strength=0.06)


def camera(scene: Scene, rng: random.Random, strength: float = 0.05) -> Scene:
    img = np.asarray(scene.image).astype(np.float32)
    H, W = img.shape[:2]
    j = lambda s: rng.uniform(-s, s)
    src = np.float32([[0, 0], [W, 0], [W, H], [0, H]])
    dst = np.float32([[W * j(strength), H * j(strength)], [W * (1 + j(strength)), H * j(strength)],
                      [W * (1 + j(strength)), H * (1 + j(strength))], [W * j(strength), H * (1 + j(strength))]])
    M = cv2.getPerspectiveTransform(src, dst)
    warped = cv2.warpPerspective(img, M, (W, H), borderMode=cv2.BORDER_REFLECT)
    # soft light falloff
    yy, xx = np.mgrid[0:H, 0:W]
    cx, cy = W * rng.uniform(0.3, 0.7), H * rng.uniform(0.2, 0.6)
    fall = 1 - 0.18 * (((xx - cx) / W) ** 2 + ((yy - cy) / H) ** 2) * 2
    warped = np.clip(warped * fall[..., None] + np.random.default_rng(rng.randint(0, 2**31)).normal(0, 2.5, warped.shape), 0, 255)
    boxes = _boxes_through(scene.boxes, lambda c: _warp_points(c, M))
    return Scene(Image.fromarray(warped.astype(np.uint8)), boxes)


def _background(W: int, H: int, rng: random.Random, wood: bool = False) -> np.ndarray:
    base = np.array((196, 170, 136) if wood else (214, 218, 222), np.float32)
    g = np.random.default_rng(rng.randint(0, 2**31))
    arr = np.zeros((H, W, 3), np.float32) + base
    if wood:
        stripes = np.sin(np.linspace(0, 40, W)[None, :] + g.normal(0, 0.3, (H, 1)).cumsum(0) * 0.02)
        arr += stripes[..., None] * 10
    arr += g.normal(0, 3, (H, W, 1))
    grad = np.linspace(1.06, 0.9, H)[:, None, None]
    return arr * grad


# ----------------------------------------------------------------------------- perturbations
PERTURBATIONS = ["clean", "blur", "motion_blur", "glare", "shadow", "jpeg", "occlusion", "rotation", "low_res", "perspective"]


def perturb(scene: Scene, kind: str, seed: int = 0, severity: float = 1.0) -> Scene:
    rng = random.Random(f"{kind}-{seed}")
    img = np.asarray(scene.image).astype(np.float32)
    H, W = img.shape[:2]
    boxes = scene.boxes
    if kind == "clean":
        pass
    elif kind == "blur":
        img = cv2.GaussianBlur(img, (0, 0), 1.2 + 1.6 * severity)
    elif kind == "motion_blur":
        k = int(7 + 12 * severity)
        kern = np.zeros((k, k), np.float32)
        kern[k // 2, :] = 1 / k
        rot = cv2.getRotationMatrix2D((k / 2, k / 2), rng.uniform(0, 180), 1)
        kern = cv2.warpAffine(kern, rot, (k, k))
        kern /= kern.sum()
        img = cv2.filter2D(img, -1, kern)
    elif kind == "glare":
        # a specular highlight centred on a random text field
        target = rng.choice(boxes) if boxes else None
        cx = (target.x0 + target.x1) / 2 if target else W / 2
        cy = (target.y0 + target.y1) / 2 if target else H / 2
        yy, xx = np.mgrid[0:H, 0:W]
        r = (0.06 + 0.06 * severity) * max(W, H)
        spot = np.exp(-(((xx - cx) ** 2 + ((yy - cy) * 1.6) ** 2) / (2 * r * r)))
        img = np.clip(img + spot[..., None] * 255 * (0.8 + 0.4 * severity), 0, 255)
    elif kind == "shadow":
        yy, xx = np.mgrid[0:H, 0:W]
        a, b = rng.uniform(-1, 1), rng.uniform(0.2, 0.8)
        m = (yy / H) > (a * (xx / W - 0.5) + b)
        img = img * np.where(m, 1 - 0.45 * severity, 1.0)[..., None]
    elif kind == "jpeg":
        q = int(max(5, 30 - 22 * severity))
        ok, enc = cv2.imencode(".jpg", img.astype(np.uint8), [cv2.IMWRITE_JPEG_QUALITY, q])
        img = cv2.imdecode(enc, cv2.IMREAD_UNCHANGED).astype(np.float32)
    elif kind == "occlusion":
        target = rng.choice(boxes) if boxes else None
        if target:
            cx, cy = (target.x0 + target.x1) / 2, (target.y0 + target.y1) / 2
            ax, ay = (target.x1 - target.x0) * (0.35 + 0.25 * severity), (target.y1 - target.y0) * 1.6
            cv2.ellipse(img, (int(cx), int(cy)), (int(ax), int(ay)), rng.uniform(-30, 30), 0, 360, (190, 150, 130), -1)
    elif kind == "rotation":
        ang = rng.choice([-1, 1]) * (4 + 8 * severity)
        M = cv2.getRotationMatrix2D((W / 2, H / 2), ang, 1.0)
        img = cv2.warpAffine(img, M, (W, H), borderMode=cv2.BORDER_REFLECT)
        M3 = np.vstack([M, [0, 0, 1]]).astype(np.float32)
        boxes = _boxes_through(boxes, lambda c: _warp_points(c, M3))
    elif kind == "low_res":
        f = 0.45 - 0.2 * severity
        small = cv2.resize(img, (int(W * f), int(H * f)), interpolation=cv2.INTER_AREA)
        img = cv2.resize(small, (W, H), interpolation=cv2.INTER_LINEAR)
    elif kind == "perspective":
        return camera(scene, rng, strength=0.08 + 0.06 * severity)
    else:
        raise ValueError(kind)
    return Scene(Image.fromarray(np.clip(img, 0, 255).astype(np.uint8)), boxes)
