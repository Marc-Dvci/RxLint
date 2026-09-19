"""Deterministic image-quality checks shown the moment a photo is added."""

from __future__ import annotations

import io
from typing import Any

import cv2
import numpy as np
from PIL import Image


def assess(image_bytes: bytes) -> dict[str, Any]:
    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    w, h = img.size
    arr = np.asarray(img)
    gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
    scale = 1000 / max(w, h)
    small = cv2.resize(gray, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA) if scale < 1 else gray
    sharpness = float(cv2.Laplacian(small, cv2.CV_64F).var())
    saturated = float((gray >= 250).mean())
    # glare: large bright connected blobs, not white paper margins
    bright = (gray >= 245).astype(np.uint8)
    n, _, stats, _ = cv2.connectedComponentsWithStats(bright, 8)
    blob = max((s[cv2.CC_STAT_AREA] for s in stats[1:]), default=0) / (w * h)
    mean = float(gray.mean())
    checks = [
        {"id": "resolution", "ok": min(w, h) >= 600, "value": f"{w}x{h}", "message": "Resolution is low; move closer." if min(w, h) < 600 else "Resolution OK"},
        {"id": "blur", "ok": sharpness >= 60, "value": round(sharpness, 1), "message": "Image looks blurred; hold steady." if sharpness < 60 else "Sharp"},
        {"id": "glare", "ok": blob < 0.04, "value": round(blob, 4), "message": "Glare over part of the image; tilt away from the light." if blob >= 0.04 else "No glare"},
        {"id": "exposure", "ok": 50 <= mean <= 235, "value": round(mean, 1), "message": "Too dark or too bright." if not 50 <= mean <= 235 else "Exposure OK"},
    ]
    return {"width": w, "height": h, "checks": checks, "ok": all(c["ok"] for c in checks), "saturated_fraction": round(saturated, 4)}
