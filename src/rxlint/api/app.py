"""RxLint HTTP API and static web app."""

from __future__ import annotations

import asyncio
import functools
import json
import os
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from .. import demo
from ..config import load_env
from ..core import build_snapshot, load_pack, verify
from ..core.rulepack import verify_quotes
from ..core.snapshot import FIELD_MAP
from ..live.drift import drift_check
from ..live.surveillance import live_check, policies
from ..live.tavily import TavilyClient
from ..models.client import ModelClient, role_config
from ..pipeline import Asset, CaseInput, assess, perception_mode, run_case
from ..reasoning.explain import explain
from ..reasoning.i18n import LANGUAGES
from . import guard, report

ROOT = Path(__file__).resolve().parents[3]
DATA = Path(os.environ.get("RXLINT_DATA", ROOT / "data"))
CASES = DATA / "cases"
FIXTURES = ROOT / "fixtures" / "demo_cases"
WEB = ROOT / "web" / "dist"
BENCH = ROOT / "benchmarks" / "results"

load_env()
app = FastAPI(title="RxLint", version="0.1.0", docs_url="/api/docs", openapi_url="/api/openapi.json")
PACK = load_pack()
_events: dict[str, list[dict[str, Any]]] = {}
_lock = threading.Lock()


def _client() -> ModelClient:
    return ModelClient(mode=os.environ.get("RXLINT_MODEL_MODE", "auto"))


def _case_dir(case_id: str) -> Path:
    if not case_id.replace("-", "").replace("_", "").isalnum():
        raise HTTPException(400, "bad case id")
    return CASES / case_id


def _push(case_id: str, kind: str, data: dict[str, Any]) -> None:
    with _lock:
        _events.setdefault(case_id, []).append({"event": kind, "data": data, "t": time.time()})


def _save(case_id: str, name: str, obj: Any) -> None:
    d = _case_dir(case_id)
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text(json.dumps(obj, ensure_ascii=False, default=str), encoding="utf-8")


def _load(case_id: str, name: str) -> Any:
    p = _case_dir(case_id) / name
    if not p.exists():
        raise HTTPException(404, f"{name} not found for {case_id}")
    return json.loads(p.read_text(encoding="utf-8"))


# ----------------------------------------------------------------------------- status
def omni_served() -> bool:
    """Nemotron 3 Nano Omni is not on Token Factory: it is used only where RXLINT_OMNI_BASE_URL points at a
    server that hosts it (a Nebius AI Cloud endpoint or llama.cpp)."""
    return bool(os.environ.get("RXLINT_OMNI_BASE_URL"))


@app.get("/api/health")
def health() -> dict[str, Any]:
    roles = {}
    for role in ("omni", "vision", "structure", "ultra"):
        cfg = role_config(role)
        roles[role] = {"model": cfg.model, "provider": cfg.provider, "configured": bool(cfg.api_key) or cfg.provider == "local-llama.cpp"}
    if not omni_served():
        roles["omni"] = {"model": role_config("omni").model, "provider": None, "configured": False,
                         "note": "not served on Token Factory; set RXLINT_OMNI_BASE_URL to a Nebius AI Cloud endpoint or llama.cpp"}
    return {
        "status": "ok",
        "rulepack": PACK.summary_dict(),
        "models": roles,
        "voice": omni_served(),
        "perception": {"mode": perception_mode(),
                       "readers": [role_config("omni").model] if perception_mode() == "omni"
                       else [role_config("vision").model, role_config("structure").model]},
        "model_mode": os.environ.get("RXLINT_MODEL_MODE", "auto"),
        "tavily": {"configured": TavilyClient().configured},
        "languages": LANGUAGES,
        "countries": {k: v["name"] for k, v in policies()["countries"].items()},
        "time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


@app.get("/api/demo-cases")
def demo_cases() -> list[dict[str, Any]]:
    return [c.meta() for c in demo.CASES]


@app.get("/api/demo-cases/{cid}/{name}")
def demo_asset(cid: str, name: str, w: int | None = None):
    if cid not in demo.BY_ID or name not in ("rx.jpg", "label.jpg"):
        raise HTTPException(404)
    p = demo.photo(cid, name.split(".")[0])
    if w:
        return Response(_thumbnail(str(p), max(64, min(int(w), 800))), media_type="image/jpeg",
                        headers={"Cache-Control": "public, max-age=86400"})
    return FileResponse(p, media_type=demo.mime(p))


@functools.lru_cache(maxsize=64)
def _thumbnail(path: str, width: int) -> bytes:
    from io import BytesIO

    from PIL import Image

    im = Image.open(path).convert("RGB")
    im.thumbnail((width, width * 2))
    buf = BytesIO()
    im.save(buf, "JPEG", quality=82, optimize=True)
    return buf.getvalue()


# ----------------------------------------------------------------------------- cases
def _start(inp: CaseInput, blobs: dict[str, bytes], meta: dict[str, Any]) -> None:
    case_id = inp.case_id
    _save(case_id, "input.json", {**inp.model_dump(), "meta": meta})
    for a in inp.assets:
        (_case_dir(case_id) / f"asset_{a.id}").write_bytes(blobs[a.id])
    _push(case_id, "created", {"case_id": case_id, "assets": [a.model_dump() for a in inp.assets]})

    def work() -> None:
        try:
            client = _client()
            res = run_case(inp, blobs, client, PACK, emit=lambda k, d: _push(case_id, k, d))
            _save(case_id, "result.json", res.model_dump())
            _push(case_id, "done", {"state": res.verification["state"]})
        except Exception as exc:  # surfaced to the UI as a failed run
            _push(case_id, "error", {"message": f"{type(exc).__name__}: {exc}"})

    threading.Thread(target=work, daemon=True).start()


PATIENT_FIELDS = {k for k in FIELD_MAP if k.startswith("patient.")}
IMAGE_MIME = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}


def _image_mime(data: bytes) -> str:
    """The media type of an uploaded photo, read from its bytes; the declared type is not trusted."""
    from io import BytesIO

    from PIL import Image, UnidentifiedImageError

    try:
        with Image.open(BytesIO(data)) as im:
            fmt = (im.format or "").upper()
    except (UnidentifiedImageError, OSError):
        raise HTTPException(415, "unsupported image format: send a JPEG, PNG or WebP photo") from None
    return IMAGE_MIME.get(fmt, "image/jpeg")


@app.post("/api/cases")
async def create_case(
    request: Request,
    prescription: UploadFile | None = File(None),
    medicine: UploadFile | None = File(None),
    audio: UploadFile | None = File(None),
    patient: str = Form("{}"),
    country: str = Form("FR"),
    dispense_date: str | None = Form(None),
    demo_id: str | None = Form(None),
) -> dict[str, Any]:
    case_id = f"c_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    blobs: dict[str, bytes] = {}
    assets: list[Asset] = []
    meta: dict[str, Any] = {}
    if demo_id:
        c = demo.BY_ID.get(demo_id)
        if c is None:
            raise HTTPException(404, "unknown demo case")
        for aid, kind in (("rx", "prescription"), ("label", "medicine")):
            p = demo.photo(demo_id, aid)
            data = p.read_bytes()
            blobs[aid] = data
            assets.append(Asset.from_bytes(aid, kind, data, demo.mime(p), p.name))
        pat = dict(c.patient)
        pat.update(json.loads(patient or "{}"))
        country, dispense_date = c.country, dispense_date or c.dispense_date
        meta = {"demo": c.meta()}
    else:
        guard.check(request, "upload")
        for aid, kind, up in (("rx", "prescription", prescription), ("label", "medicine", medicine), ("voice", "audio", audio)):
            if up is None:
                continue
            data = await up.read()
            if len(data) > 12 * 1024 * 1024:
                raise HTTPException(413, "file too large")
            mime = up.content_type or "application/octet-stream"
            if kind == "audio" and not omni_served():
                raise HTTPException(400, "voice notes need Nemotron 3 Nano Omni, which this deployment does not serve")
            if kind != "audio":
                mime = _image_mime(data)
            blobs[aid] = data
            assets.append(Asset.from_bytes(aid, kind, data, mime, up.filename))
        if not any(a.kind in ("prescription", "medicine") for a in assets):
            raise HTTPException(400, "add at least one photo")
        try:
            pat = json.loads(patient or "{}")
        except json.JSONDecodeError:
            raise HTTPException(400, "patient must be a JSON object") from None
    unknown = sorted(k for k in pat if k not in PATIENT_FIELDS)
    if unknown:
        raise HTTPException(400, f"unknown patient field(s) {unknown}; use {sorted(PATIENT_FIELDS)}")
    inp = CaseInput(case_id=case_id, assets=assets, patient={k: v for k, v in pat.items() if v}, country=country,
                    dispense_date=dispense_date)
    _start(inp, blobs, meta)
    return {"case_id": case_id}


@app.get("/api/cases/{case_id}/events")
async def case_events(case_id: str):
    async def gen():
        i = 0
        deadline = time.time() + 600
        while time.time() < deadline:
            with _lock:
                items = list(_events.get(case_id, []))
            while i < len(items):
                ev = items[i]
                i += 1
                yield {"event": ev["event"], "data": json.dumps(ev["data"], default=str)}
                if ev["event"] in ("done", "error"):
                    return
            await asyncio.sleep(0.25)

    return EventSourceResponse(gen())


@app.get("/api/cases/{case_id}")
def get_case(case_id: str) -> dict[str, Any]:
    inp = _load(case_id, "input.json")
    d = _case_dir(case_id)
    out: dict[str, Any] = {"input": inp, "status": "running"}
    if (d / "result.json").exists():
        out["result"] = json.loads((d / "result.json").read_text(encoding="utf-8"))
        out["status"] = "done"
    for name in ("live.json", "explanations.json"):
        if (d / name).exists():
            out[name.split(".")[0]] = json.loads((d / name).read_text(encoding="utf-8"))
    with _lock:
        out["events"] = [e["event"] for e in _events.get(case_id, [])]
    return out


@app.get("/api/cases/{case_id}/assets/{asset_id}")
def case_asset(case_id: str, asset_id: str):
    inp = _load(case_id, "input.json")
    a = next((x for x in inp["assets"] if x["id"] == asset_id), None)
    if a is None:
        raise HTTPException(404)
    return Response((_case_dir(case_id) / f"asset_{asset_id}").read_bytes(), media_type=a["mime"])


class Confirmation(BaseModel):
    confirmations: dict[str, str]


@app.post("/api/cases/{case_id}/confirm")
def confirm(case_id: str, body: Confirmation) -> dict[str, Any]:
    inp_raw = _load(case_id, "input.json")
    res = _load(case_id, "result.json")
    inp = CaseInput(**{k: v for k, v in inp_raw.items() if k != "meta"})
    inp.confirmations.update({k: v for k, v in body.confirmations.items() if v})
    perception = {"quality": res["quality"], "extractions": res["extractions"], "speech": res["speech"],
                  "observations": res["observations"], "untrusted_text_flagged": res["untrusted_text_flagged"]}
    new = assess(inp, perception, _client(), PACK)
    out = new.model_dump()
    out["model_calls"] = res["model_calls"] + out["model_calls"]
    _save(case_id, "input.json", {**inp.model_dump(), "meta": inp_raw.get("meta", {})})
    _save(case_id, "result.json", out)
    return out


class ExplainRequest(BaseModel):
    language: str = "en"
    audience: str = "caregiver"


@app.post("/api/cases/{case_id}/explain")
def explain_case(case_id: str, body: ExplainRequest, request: Request) -> dict[str, Any]:
    if body.language not in LANGUAGES or body.audience not in ("caregiver", "professional"):
        raise HTTPException(400, "unsupported language or audience")
    res = _load(case_id, "result.json")
    d = _case_dir(case_id)
    cache = json.loads((d / "explanations.json").read_text(encoding="utf-8")) if (d / "explanations.json").exists() else {}
    key = f"{body.audience}:{body.language}:{res['verification']['result_sha256']}"
    if key not in cache:
        guard.check(request, "explain")
        cache[key] = explain(_client(), res["verification"], body.language, body.audience)
        _save(case_id, "explanations.json", cache)
    return cache[key]


LIVE_CACHE = guard.LiveCache(DATA / "live_cache")


@app.post("/api/cases/{case_id}/live")
def live_case(case_id: str, request: Request) -> dict[str, Any]:
    inp = _load(case_id, "input.json")
    res = _load(case_id, "result.json")
    facts = {k: v for k, v in _facts(res).items()}
    product = facts.get("dispensed.product") or facts.get("rx.product")
    key = {"product": product, "lot": facts.get("dispensed.lot"), "country": inp.get("country"), "as_of": inp.get("dispense_date"),
           "policy": policies()["version"]}
    out = LIVE_CACHE.get(key)
    if out is None:
        guard.check(request, "live")
        out = live_check(PACK, product, facts.get("dispensed.lot"), inp.get("country"), facts.get("dispensed.manufacturer"),
                         as_of=inp.get("dispense_date"))
        LIVE_CACHE.put(key, out)
    _save(case_id, "live.json", out)
    return out


def _facts(res: dict[str, Any]) -> dict[str, Any]:
    ev = res["verification"]["evidence"]
    out = {}
    for key in ("rx.product", "dispensed.product", "dispensed.lot", "dispensed.manufacturer"):
        node = ev.get(f"ev_{key.replace('.', '_')}")
        if node and node.get("status") in ("normalized", "derived"):
            out[key] = node.get("value")
    return out


@app.get("/api/cases/{case_id}/report")
def case_report(case_id: str, format: str = "html"):
    inp = _load(case_id, "input.json")
    res = _load(case_id, "result.json")
    d = _case_dir(case_id)
    live = json.loads((d / "live.json").read_text(encoding="utf-8")) if (d / "live.json").exists() else None
    bundle = report.bundle(case_id, inp, res, live, PACK)
    if format == "json":
        return JSONResponse(bundle, headers={"Content-Disposition": f'attachment; filename="rxlint-{case_id}.json"'})
    return HTMLResponse(report.render_html(bundle))


# ----------------------------------------------------------------------------- manual verification
class ManualRequest(BaseModel):
    fields: dict[str, str]
    dispense_date: str | None = None


@app.post("/api/verify")
def manual_verify(body: ManualRequest) -> dict[str, Any]:
    snap = build_snapshot({k: v for k, v in body.fields.items() if v}, PACK, case_id="manual", dispense_date=body.dispense_date)
    return verify(snap, PACK).model_dump()


# ----------------------------------------------------------------------------- rule pack
@app.get("/api/rulepack")
def rulepack() -> dict[str, Any]:
    quotes = verify_quotes(PACK)
    ok = {r["rule"] for r in quotes if r["found"]}
    bad = {r["rule"] for r in quotes if not r["found"]}
    return {
        **PACK.summary_dict(), "summary": PACK.summary, "scope": PACK.scope, "policies": PACK.policies,
        "sources": {k: {kk: vv for kk, vv in v.items() if kk not in ("page_text",)} for k, v in PACK.sources.items()},
        "quotes_checked": len(quotes), "quotes_verified": sum(1 for r in quotes if r["found"]),
        "rules": [{**r.model_dump(), "quote_verified": (r.id in ok and r.id not in bad) if r.source.quotes or r.related_sources else None}
                  for r in PACK.rules],
    }


@app.post("/api/rulepack/drift")
def rulepack_drift(request: Request, source: str = "WHO-AWARE-2022") -> dict[str, Any]:
    if source not in PACK.sources or "monitoring" not in PACK.sources[source]:
        raise HTTPException(404, "source is not monitored")
    guard.check(request, "drift")
    out = drift_check(PACK, source, client=_client())
    DATA.mkdir(parents=True, exist_ok=True)
    (DATA / "drift_last.json").write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    return out


@app.get("/api/rulepack/drift")
def rulepack_drift_last() -> dict[str, Any]:
    p = DATA / "drift_last.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {"status": "NOT_RUN"}


@app.get("/api/bench")
def bench() -> dict[str, Any]:
    p = BENCH / "summary.json"
    if not p.exists():
        return {"status": "NOT_RUN"}
    return json.loads(p.read_text(encoding="utf-8"))


# ----------------------------------------------------------------------------- web app
if WEB.exists():
    app.mount("/assets", StaticFiles(directory=WEB / "assets"), name="assets")

    WEB_ROOT = WEB.resolve()

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path.startswith("api/"):
            raise HTTPException(404)
        target = (WEB_ROOT / path).resolve()
        # Serve only files inside the built web bundle; anything else gets the app shell.
        if path and target.is_file() and target.is_relative_to(WEB_ROOT):
            return FileResponse(target)
        return FileResponse(WEB_ROOT / "index.html")
