"""Load ``.env`` from the repository root without overriding variables already set."""

from __future__ import annotations

import os
from pathlib import Path


def load_env(path: Path | None = None) -> None:
    if os.environ.get("RXLINT_LOAD_DOTENV", "1") == "0":
        return
    p = path or Path(__file__).resolve().parents[2] / ".env"
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if k and v and k not in os.environ:
            os.environ[k] = v
