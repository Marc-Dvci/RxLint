"""End-to-end case processing: photos and patient facts in, verification out.

Steps: quality checks -> Nano Omni extraction (both images in parallel) -> OCR grounding ->
deterministic normalisation -> kernel verification -> Ultra clarification when evidence is
missing or contradictory. Each step emits an event so the UI can show progress live.
"""

from __future__ import annotations

import hashlib
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from typing import Any, Callable

from pydantic import BaseModel, Field

from .core import EvidenceKind, Normalizer, Observation, SnapshotBuilder, load_pack, verify
from .core.engine import Verification
from .core.rulepack import RulePack
from .models.client import ModelClient
from .perception import grounding, quality, reliability
from .perception.extraction import Extraction, SpeechExtraction, extract_image, extract_speech
from .perception.transcribe import extract_two_stage
from .reasoning.clarify import clarify

Emit = Callable[[str, dict[str, Any]], None]


class Asset(BaseModel):
    id: str
    kind: str  # prescription | medicine | audio
    filename: str | None = None
    mime: str = "image/png"
    sha256: str
    size: int

    @staticmethod
    def from_bytes(asset_id: str, kind: str, data: bytes, mime: str, filename: str | None = None) -> "Asset":
        return Asset(id=asset_id, kind=kind, filename=filename, mime=mime, sha256=hashlib.sha256(data).hexdigest(), size=len(data))


class CaseInput(BaseModel):
    case_id: str
    assets: list[Asset]
    patient: dict[str, str] = Field(default_factory=dict)  # typed facts: patient.weight, patient.age, ...
    confirmations: dict[str, str] = Field(default_factory=dict)  # pharmacist-confirmed readings, e.g. {"rx.dose": "5 mL"}
    country: str | None = None
    dispense_date: str | None = None


class CaseResult(BaseModel):
    case_id: str
    assets: list[Asset]
    quality: dict[str, Any]
    extractions: list[dict[str, Any]]
    speech: list[dict[str, Any]]
    observations: list[dict[str, Any]]
    verification: dict[str, Any]
    clarification: dict[str, Any] | None
    model_calls: list[dict[str, Any]]
    timings_ms: dict[str, int]
    untrusted_text_flagged: bool = False


def _obs_from_extraction(ex: Extraction, lines: list[grounding.OcrLine] | None, image: bytes | None = None,
                         pack: RulePack | None = None) -> list[dict[str, Any]]:
    raw = [o.model_dump() for o in ex.observations]
    if lines is not None:
        raw = grounding.ground(raw, lines)
        if image is not None and pack is not None:
            doc = {"legibility": ex.legibility, "ocr_mean": sum(l.score for l in lines) / len(lines) if lines else 0.0}
            raw = reliability.apply(raw, ex.kind, doc, image, Normalizer(pack))
    for r in raw:
        r["asset_id"] = ex.asset_id
        r["method"] = f"{ex.model or 'model'} via {ex.provider or '?'}" + (" (replay)" if ex.replayed else "")
    # The OCR engine is a second reader for medicine names: its text is parsed by the same normaliser.
    extra = []
    for r in raw:
        if r["field"] in ("rx.drug", "dispensed.drug", "rx.indication") and r.get("grounding") == "ocr" and r.get("ocr_text"):
            extra.append({"field": r["field"], "text": r["ocr_text"], "asset_id": ex.asset_id, "bbox": r.get("bbox"),
                          "grounding": "ocr", "method": "rapidocr (second reader)", "kind": "VISUAL_OBSERVATION"})
    return raw + extra


def run_case(inp: CaseInput, blobs: dict[str, bytes], client: ModelClient, pack: RulePack | None = None,
             emit: Emit | None = None, use_ultra: bool = True) -> CaseResult:
    pack = pack or load_pack()
    emit = emit or (lambda *_: None)
    timings: dict[str, int] = {}
    t_all = time.perf_counter()
    images = [a for a in inp.assets if a.kind in ("prescription", "medicine")]
    audios = [a for a in inp.assets if a.kind == "audio"]

    t = time.perf_counter()
    q = {a.id: quality.assess(blobs[a.id]) for a in images}
    timings["quality"] = int((time.perf_counter() - t) * 1000)
    emit("quality", {"quality": q})

    # Perception: extraction and OCR run concurrently per image.
    t = time.perf_counter()
    mode = perception_mode()
    readers = [client.config("omni").model] if mode == "omni" else [client.config("vision").model, client.config("structure").model]
    emit("extract.start", {"assets": [a.id for a in images], "mode": mode, "models": readers,
                           "provider": client.config("omni" if mode == "omni" else "structure").provider})
    with ThreadPoolExecutor(max_workers=4) as pool:
        reader = extract_image if perception_mode() == "omni" else extract_two_stage
        ex_f = {a.id: pool.submit(reader, client, blobs[a.id], a.kind, a.id, a.mime) for a in images}
        ocr_f = {a.id: pool.submit(_safe_ocr, blobs[a.id]) for a in images}
        sp_f = {a.id: pool.submit(extract_speech, client, *to_wav(blobs[a.id], a.mime), a.id) for a in audios}
        extractions = {k: f.result() for k, f in ex_f.items()}
        ocr = {k: f.result() for k, f in ocr_f.items()}
        speech: dict[str, SpeechExtraction] = {k: f.result() for k, f in sp_f.items()}
    timings["perception"] = int((time.perf_counter() - t) * 1000)
    for a in images:
        ex = extractions[a.id]
        emit("extract.done", {"asset": a.id, "observations": len(ex.observations), "error": ex.error,
                              "latency_ms": ex.latency_ms, "replayed": ex.replayed})

    all_obs: list[dict[str, Any]] = []
    flagged = False
    for a in images:
        ex = extractions[a.id]
        flagged |= ex.untrusted_instructions_seen
        all_obs.extend(_obs_from_extraction(ex, ocr[a.id], blobs[a.id], pack))
    for a in audios:
        sp = speech[a.id]
        for f in sp.facts:
            all_obs.append({"field": f["field"], "text": f["text"], "quote": f["quote"], "asset_id": a.id,
                            "kind": "SPOKEN_OBSERVATION", "method": f"{sp.model} via {sp.provider}"})
    perception = {
        "quality": q, "extractions": [e.model_dump() for e in extractions.values()],
        "speech": [s_.model_dump() for s_ in speech.values()], "observations": all_obs,
        "untrusted_text_flagged": flagged,
    }
    result = assess(inp, perception, client, pack, emit, use_ultra, timings)
    timings["total"] = int((time.perf_counter() - t_all) * 1000)
    return result


def assess(inp: CaseInput, perception: dict[str, Any], client: ModelClient | None, pack: RulePack | None = None,
           emit: Emit | None = None, use_ultra: bool = True, timings: dict[str, int] | None = None) -> CaseResult:
    """Deterministic half of the pipeline: evidence, snapshot, verdict, clarification.

    Re-run on its own when the pharmacist confirms a reading, so a confirmation never triggers
    another model call for perception.
    """
    pack = pack or load_pack()
    emit = emit or (lambda *_: None)
    timings = timings if timings is not None else {}
    t = time.perf_counter()
    builder = SnapshotBuilder(Normalizer(pack), inp.case_id)
    all_obs = [o for o in perception["observations"] if o.get("method") not in ("typed", "confirmation")]
    for ob in all_obs:
        kind = EvidenceKind(ob.get("kind", "VISUAL_OBSERVATION"))
        builder.add(Observation(field=ob["field"], raw=ob["text"], kind=kind, asset_id=ob.get("asset_id"),
                                bbox=ob.get("bbox"), grounding=ob.get("grounding"), method=ob.get("method"),
                                confidence=ob.get("confidence"), legible=ob.get("legible", True),
                                alternatives=ob.get("alternatives", []),
                                requires_confirmation=ob.get("requires_confirmation", False)))
    for field_name, raw in inp.patient.items():
        if raw is None or str(raw).strip() == "":
            continue
        builder.add(Observation(field=field_name, raw=str(raw), kind=EvidenceKind.USER_ENTERED_FACT, method="typed"))
        all_obs.append({"field": field_name, "text": str(raw), "asset_id": None, "method": "typed"})
    for field_name, raw in inp.confirmations.items():
        builder.add(Observation(field=field_name, raw=str(raw), kind=EvidenceKind.USER_ENTERED_FACT, method="confirmation"))
        all_obs.append({"field": field_name, "text": str(raw), "asset_id": None, "method": "confirmation"})
    if inp.country:
        builder.add(Observation(field="context.country", raw=inp.country, kind=EvidenceKind.USER_ENTERED_FACT, method="typed"))
    snap = builder.build(dispense_date=date.fromisoformat(inp.dispense_date) if inp.dispense_date else None)
    timings["normalize"] = int((time.perf_counter() - t) * 1000)
    emit("normalize", {"facts": {k: f.status for k, f in snap.facts.items()}})

    t = time.perf_counter()
    result: Verification = verify(snap, pack)
    timings["verify"] = int((time.perf_counter() - t) * 1000)
    emit("verify", {"state": result.state, "summary": result.summary, "result_sha256": result.result_sha256})

    clar = result.clarification
    if clar and use_ultra and client is not None:
        t = time.perf_counter()
        emit("clarify.start", {"model": client.config("ultra").model})
        clar = clarify(client, result, all_obs, perception["quality"])
        timings["clarify"] = int((time.perf_counter() - t) * 1000)
        emit("clarify.done", {"clarification": clar})

    return CaseResult(
        case_id=inp.case_id,
        assets=inp.assets,
        quality=perception["quality"],
        extractions=perception["extractions"],
        speech=perception["speech"],
        observations=all_obs,
        verification=result.model_dump(),
        clarification=clar,
        model_calls=[r.as_dict() for r in client.log] if client is not None else [],
        timings_ms=timings,
        untrusted_text_flagged=perception["untrusted_text_flagged"],
    )


def perception_mode() -> str:
    """``omni``: Nemotron 3 Nano Omni reads the photo (local llama.cpp or a Nebius AI Cloud endpoint).
    ``two_stage``: a Token Factory vision model transcribes and Nemotron structures the transcript."""
    import os

    mode = os.environ.get("RXLINT_PERCEPTION")
    if mode in ("omni", "two_stage"):
        return mode
    return "omni" if os.environ.get("RXLINT_OMNI_BASE_URL") else "two_stage"


def to_wav(data: bytes, mime: str) -> tuple[bytes, str]:
    """Token Factory audio input takes wav or mp3; browser recordings (webm/ogg) are converted with ffmpeg."""
    kind = mime.split("/")[-1].split(";")[0]
    if kind in ("wav", "x-wav", "wave"):
        return data, "wav"
    if kind in ("mpeg", "mp3"):
        return data, "mp3"
    import subprocess

    proc = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", "pipe:0", "-ac", "1", "-ar", "16000", "-f", "wav", "pipe:1"],
                          input=data, capture_output=True, timeout=60)
    if proc.returncode != 0:
        raise RuntimeError(f"audio conversion failed: {proc.stderr.decode(errors='ignore')[:200]}")
    return proc.stdout, "wav"


def _safe_ocr(data: bytes) -> list[grounding.OcrLine] | None:
    try:
        return grounding.ocr_lines(data)
    except Exception:
        return None
