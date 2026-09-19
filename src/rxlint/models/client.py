"""OpenAI-compatible client for NVIDIA Nemotron models on Nebius Token Factory.

Three roles, each configurable independently:

* ``omni``  - Nemotron 3 Nano Omni: reads prescription and label images, transcribes speech.
* ``ultra`` - Nemotron 3 Ultra: clarification, explanation, translation, notice mapping.
* ``fast``  - Nemotron 3 Nano: short text-only structuring calls.

Every call is logged with model id, provider, latency and token usage. A cassette records
responses keyed by the exact request, so a recorded Token Factory response can be replayed
offline; replayed responses keep the provider and timestamp of the original call.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

TOKEN_FACTORY_URL = "https://api.tokenfactory.nebius.com/v1"

DEFAULT_MODELS = {
    "omni": "nvidia/Nemotron-3-Nano-Omni-30B-A3B-Reasoning",
    "vision": "deepseek-ai/DeepSeek-V4.1-Flash",
    "structure": "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B",
    "ultra": "nvidia/Nemotron-3-Ultra-550b-a55b",
    "fast": "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B",
}


class ModelUnavailable(RuntimeError):
    pass


@dataclass
class RoleConfig:
    role: str
    model: str
    base_url: str
    api_key: str | None
    provider: str
    thinking: bool = False
    json_schema: bool = True
    timeout_s: float = 120.0


@dataclass
class CallRecord:
    role: str
    model: str
    provider: str
    purpose: str
    latency_ms: int
    prompt_tokens: int | None
    completion_tokens: int | None
    ok: bool
    replayed: bool = False
    recorded_at: str | None = None
    error: str | None = None
    request_sha256: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


@dataclass
class ChatResult:
    content: str
    reasoning: str | None
    record: CallRecord
    raw: dict[str, Any] = field(default_factory=dict)


def _env(name: str, default: str | None = None) -> str | None:
    v = os.environ.get(name)
    return v if v not in (None, "") else default


def role_config(role: str) -> RoleConfig:
    up = role.upper()
    base = _env(f"RXLINT_{up}_BASE_URL", _env("RXLINT_LLM_BASE_URL", TOKEN_FACTORY_URL))
    key = _env(f"RXLINT_{up}_API_KEY", _env("NEBIUS_API_KEY"))
    model = _env(f"RXLINT_{up}_MODEL", DEFAULT_MODELS[role])
    provider = "nebius-token-factory" if "tokenfactory.nebius.com" in (base or "") else _env(f"RXLINT_{up}_PROVIDER", "openai-compatible")
    if base and ("127.0.0.1" in base or "localhost" in base):
        provider = _env(f"RXLINT_{up}_PROVIDER", "local-llama.cpp")
    return RoleConfig(
        role=role, model=model, base_url=base.rstrip("/"), api_key=key, provider=provider,
        thinking=_env(f"RXLINT_{up}_THINKING", "off") == "on",
        json_schema=_env(f"RXLINT_{up}_JSON_SCHEMA", "on") == "on",
        timeout_s=float(_env(f"RXLINT_{up}_TIMEOUT", "180")),
    )


def image_part(image_bytes: bytes, mime: str = "image/png", max_side: int = 1600) -> dict[str, Any]:
    """Encode an image for a chat message, downscaling large photos to ``max_side``."""
    from PIL import Image

    img = Image.open(io.BytesIO(image_bytes))
    img.load()
    if max(img.size) > max_side:
        img.thumbnail((max_side, max_side))
        buf = io.BytesIO()
        img.convert("RGB").save(buf, "JPEG", quality=92)
        image_bytes, mime = buf.getvalue(), "image/jpeg"
    b64 = base64.b64encode(image_bytes).decode()
    return {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}}


def audio_part(audio_bytes: bytes, fmt: str = "wav") -> dict[str, Any]:
    return {"type": "input_audio", "input_audio": {"data": base64.b64encode(audio_bytes).decode(), "format": fmt}}


def _request_key(role: str, model: str, messages: list[dict], schema: dict | None, purpose: str) -> str:
    def strip(o: Any) -> Any:
        if isinstance(o, dict):
            if o.get("type") == "image_url":
                url = o["image_url"]["url"]
                return {"type": "image", "sha256": hashlib.sha256(url.encode()).hexdigest()}
            if o.get("type") == "input_audio":
                return {"type": "audio", "sha256": hashlib.sha256(o["input_audio"]["data"].encode()).hexdigest()}
            return {k: strip(v) for k, v in o.items()}
        if isinstance(o, list):
            return [strip(x) for x in o]
        return o

    blob = json.dumps({"role": role, "model_role": role, "messages": strip(messages), "schema": schema, "purpose": purpose},
                      sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode()).hexdigest()


class Cassette:
    """Append-only JSONL store of model responses keyed by request hash."""

    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.Lock()
        self._items: dict[str, dict[str, Any]] = {}
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    rec = json.loads(line)
                    self._items[rec["key"]] = rec

    def has_role(self, role: str) -> bool:
        # Records written before roles were stored are all Nano Omni perception calls.
        return any(r.get("role", "omni") == role for r in self._items.values())

    def get(self, key: str) -> dict[str, Any] | None:
        return self._items.get(key)

    def put(self, key: str, rec: dict[str, Any]) -> None:
        with self._lock:
            rec = {"key": key, **rec}
            self._items[key] = rec
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            except OSError:
                pass  # a read-only deployment keeps the response in memory only


class ModelClient:
    """Routes chat calls to the configured provider, with optional record/replay."""

    def __init__(self, mode: str | None = None, cassette: Path | None = None):
        self.mode = mode or _env("RXLINT_MODEL_MODE", "live")  # live | record | replay | auto
        path = cassette or Path(_env("RXLINT_CASSETTE", str(Path(__file__).resolve().parents[3] / "fixtures" / "model_cassette.jsonl")))
        self.cassette = Cassette(path)
        self.log: list[CallRecord] = []
        self._http = httpx.Client(timeout=None)

    def config(self, role: str) -> RoleConfig:
        return role_config(role)

    def available(self, role: str) -> bool:
        cfg = role_config(role)
        live = bool(cfg.api_key) or cfg.provider == "local-llama.cpp"
        if self.mode == "replay":
            return self.cassette.has_role(role)
        if self.mode == "auto":
            return live or self.cassette.has_role(role)
        return live

    def chat(self, role: str, messages: list[dict], *, schema: dict | None = None, purpose: str = "",
             max_tokens: int = 2048, temperature: float = 0.0) -> ChatResult:
        cfg = role_config(role)
        key = _request_key(role, cfg.model, messages, schema, purpose)
        if self.mode in ("replay", "auto"):
            hit = self.cassette.get(key)
            if hit is not None:
                rec = CallRecord(role=role, model=hit["model"], provider=hit["provider"], purpose=purpose,
                                 latency_ms=hit.get("latency_ms", 0), prompt_tokens=hit.get("prompt_tokens"),
                                 completion_tokens=hit.get("completion_tokens"), ok=True, replayed=True,
                                 recorded_at=hit.get("recorded_at"), request_sha256=key)
                self.log.append(rec)
                return ChatResult(hit["content"], hit.get("reasoning"), rec)
            if self.mode == "replay":
                rec = CallRecord(role=role, model=cfg.model, provider="replay", purpose=purpose, latency_ms=0,
                                 prompt_tokens=None, completion_tokens=None, ok=False, error="no recorded response",
                                 request_sha256=key)
                self.log.append(rec)
                raise ModelUnavailable(f"{role}: no recorded response for this request")
        if not (cfg.api_key or cfg.provider == "local-llama.cpp"):
            rec = CallRecord(role=role, model=cfg.model, provider=cfg.provider, purpose=purpose, latency_ms=0,
                             prompt_tokens=None, completion_tokens=None, ok=False, error="NEBIUS_API_KEY not set",
                             request_sha256=key)
            self.log.append(rec)
            raise ModelUnavailable(f"{role}: NEBIUS_API_KEY is not configured")
        body: dict[str, Any] = {"model": cfg.model, "messages": messages, "max_tokens": max_tokens, "temperature": temperature}
        body["chat_template_kwargs"] = {"enable_thinking": cfg.thinking}
        if schema is not None and cfg.json_schema:
            body["response_format"] = {"type": "json_schema", "json_schema": {"name": purpose or "result", "schema": schema, "strict": True}}
        headers = {"Content-Type": "application/json"}
        if cfg.api_key:
            headers["Authorization"] = f"Bearer {cfg.api_key}"
        t0 = time.perf_counter()
        try:
            resp = self._http.post(f"{cfg.base_url}/chat/completions", json=body, headers=headers, timeout=cfg.timeout_s)
            if resp.status_code == 400 and "response_format" in body and "response_format" in resp.text:
                body.pop("response_format")
                resp = self._http.post(f"{cfg.base_url}/chat/completions", json=body, headers=headers, timeout=cfg.timeout_s)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:  # network, HTTP or decode failure
            rec = CallRecord(role=role, model=cfg.model, provider=cfg.provider, purpose=purpose,
                             latency_ms=int((time.perf_counter() - t0) * 1000), prompt_tokens=None, completion_tokens=None,
                             ok=False, error=f"{type(exc).__name__}: {str(exc)[:300]}", request_sha256=key)
            self.log.append(rec)
            raise ModelUnavailable(f"{role}: {rec.error}") from exc
        latency = int((time.perf_counter() - t0) * 1000)
        msg = data["choices"][0]["message"]
        content = msg.get("content") or ""
        reasoning = msg.get("reasoning_content") or msg.get("reasoning")
        usage = data.get("usage") or {}
        served = data.get("model") or cfg.model
        if cfg.provider == "local-llama.cpp" and served.lower().endswith(".gguf"):
            quant = re.search(r"(IQ\d_\w+?|Q\d_K_\w|Q\d_\d|MXFP4)(?=[._-]|$)", Path(served).name)
            served = f"{cfg.model} ({quant.group(1) if quant else 'GGUF'} GGUF)"
        rec = CallRecord(role=role, model=served, provider=cfg.provider, purpose=purpose,
                         latency_ms=latency, prompt_tokens=usage.get("prompt_tokens"),
                         completion_tokens=usage.get("completion_tokens"), ok=True, request_sha256=key,
                         recorded_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))
        self.log.append(rec)
        if self.mode in ("record", "auto"):
            self.cassette.put(key, {"role": role, "model": rec.model, "provider": rec.provider, "purpose": purpose, "content": content,
                                    "reasoning": reasoning, "latency_ms": latency, "prompt_tokens": rec.prompt_tokens,
                                    "completion_tokens": rec.completion_tokens, "recorded_at": rec.recorded_at})
        return ChatResult(content, reasoning, rec, data)


def parse_json(text: str, reasoning: str | None = None) -> dict[str, Any]:
    """Extract the first JSON object from a model reply (fences and preambles tolerated)."""
    for candidate in (text, reasoning or ""):
        if not candidate:
            continue
        t = re.sub(r"^```(?:json)?|```$", "", candidate.strip(), flags=re.M).strip()
        try:
            obj = json.loads(t)
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            pass
        start = t.find("{")
        while start != -1:
            depth, in_str, esc = 0, False, False
            for i in range(start, len(t)):
                ch = t[i]
                if in_str:
                    if esc:
                        esc = False
                    elif ch == "\\":
                        esc = True
                    elif ch == '"':
                        in_str = False
                elif ch == '"':
                    in_str = True
                elif ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        try:
                            obj = json.loads(t[start:i + 1])
                            if isinstance(obj, dict):
                                return obj
                        except json.JSONDecodeError:
                            break
                        break
            start = t.find("{", start + 1)
    raise ValueError("no JSON object in model reply")
