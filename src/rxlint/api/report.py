"""Verification report: a JSON bundle and a printable HTML rendering of the same bundle."""

from __future__ import annotations

import html as _html
from datetime import datetime, timezone
from typing import Any

from ..core.engine import ENGINE_VERSION
from ..core.rulepack import RulePack


def bundle(case_id: str, inp: dict[str, Any], res: dict[str, Any], live: dict[str, Any] | None, pack: RulePack) -> dict[str, Any]:
    v = res["verification"]
    return {
        "report_version": "1",
        "case_id": case_id,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "state": v["state"],
        "summary": v["summary"],
        "assets": inp.get("assets", []),
        "patient_context": inp.get("patient", {}),
        "confirmations": inp.get("confirmations", {}),
        "country": inp.get("country"),
        "dispense_date": inp.get("dispense_date"),
        "findings": [{k: f[k] for k in ("rule_id", "rule_version", "title", "status", "severity", "message", "facts",
                                        "calculations", "evidence", "action", "policies")} | {"source": f.get("source", {}).get("primary")}
                     for f in v["findings"]],
        "coverage": v["coverage"],
        "clarification": res.get("clarification"),
        "evidence": v["evidence"],
        "live_intelligence": live,
        "rulepack": {**pack.summary_dict()},
        "engine": ENGINE_VERSION,
        "hashes": {"snapshot_sha256": v["snapshot_sha256"], "result_sha256": v["result_sha256"], "rulepack_sha256": pack.sha256,
                   "assets": {a["id"]: a["sha256"] for a in inp.get("assets", [])}},
        "models": [{k: c.get(k) for k in ("role", "model", "provider", "purpose", "latency_ms", "replayed", "recorded_at", "ok")}
                   for c in res.get("model_calls", [])],
        "professional_approval": {"name": None, "signature": None, "decision": None, "time": None},
        "disclaimer": "Research prototype. Not approved for clinical use. A PASS means no discrepancy was detected within the scope of the installed rule pack.",
    }


STATE_COLOR = {"PASS": "#177245", "REVIEW": "#b3261e", "CANNOT_VERIFY": "#8a5a00", "OUT_OF_SCOPE": "#4a5568"}


def render_html(b: dict[str, Any]) -> str:
    e = _esc
    rows = []
    for f in b["findings"]:
        if f["status"] in ("not_applicable",):
            continue
        calc = "<br>".join(e(s) for c in f["calculations"] for s in c.get("steps", []))
        src = f.get("source") or {}
        loc = src.get("locator")
        loc_txt = ", ".join(f"{k} {v}" for k, v in loc.items()) if isinstance(loc, dict) else (loc or "")
        quote = "<br>".join(f"&ldquo;{e(q)}&rdquo;" for q in (src.get("quotes") or [])[:2])
        rows.append(f"""<tr class="s-{e(f['status'])}"><td><code>{e(f['rule_id'])}</code><br><small>v{e(f['rule_version'])}</small></td>
<td>{e(f['status'].replace('_', ' '))}{'<br><b>' + e(f['severity']) + '</b>' if f.get('severity') else ''}</td>
<td>{e(f['message'])}{'<div class="calc">' + calc + '</div>' if calc else ''}</td>
<td><small>{e(src.get('title') or '')} {e(loc_txt)}<br>{quote}</small></td></tr>""")
    live = b.get("live_intelligence")
    live_html = "<p>Not run.</p>"
    if live:
        items = "".join(f"<li><b>{e(n['match_type'])}</b> {e(n.get('authority') or '')}: {e(n['title'])} <small>{e(n.get('published_at') or '')}</small><br><small>{e(n['url'])}</small></li>"
                        for n in live.get("notices", [])[:6])
        live_html = f"<p><b>{e(live['status'])}</b> {e(live.get('statement') or live.get('reason') or '')}</p><ul>{items}</ul>"
    models = "".join(f"<tr><td>{e(m['role'] or '')}</td><td><code>{e(m['model'] or '')}</code></td><td>{e(m['provider'] or '')}{' (replay)' if m.get('replayed') else ''}</td><td>{e(m['purpose'] or '')}</td><td>{m.get('latency_ms') or ''} ms</td></tr>" for m in b["models"])
    color = STATE_COLOR.get(b["state"], "#333")
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>RxLint report {e(b['case_id'])}</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
body{{font:14px/1.5 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;color:#1d2330;margin:32px auto;max-width:1000px;padding:0 16px}}
h1{{font-size:22px;margin:0}} h2{{font-size:15px;margin-top:28px;border-bottom:1px solid #dde2ea;padding-bottom:4px}}
.state{{display:inline-block;padding:6px 14px;border-radius:6px;color:#fff;background:{color};font-weight:700;letter-spacing:.04em}}
table{{border-collapse:collapse;width:100%}} td,th{{border-bottom:1px solid #eef1f5;padding:8px 6px;vertical-align:top;text-align:left}}
tr.s-fail td:first-child{{border-left:3px solid #b3261e}} tr.s-cannot_evaluate td:first-child{{border-left:3px solid #8a5a00}}
.calc{{font-family:ui-monospace,Consolas,monospace;font-size:12px;background:#f5f7fa;padding:6px;margin-top:6px;border-radius:4px}}
code{{font-size:12px}} .muted{{color:#5b6472}} .sign{{display:grid;grid-template-columns:1fr 1fr;gap:24px;margin-top:16px}}
.sign div{{border-bottom:1px solid #999;height:40px}} @media print{{body{{margin:0}}}}
</style></head><body>
<p class="muted">RxLint verification report &middot; {e(b['generated_at'])}</p>
<h1>Case {e(b['case_id'])} &nbsp; <span class="state">{e(b['state'].replace('_', ' '))}</span></h1>
<p>{b['summary']['review']} require review &middot; {b['summary']['passed']} checks passed &middot; {b['summary']['cannot_verify']} cannot verify &middot; {b['summary']['notes']} notes</p>
<p class="muted">Rule pack <code>{e(b['rulepack']['id'])}</code> {e(b['rulepack']['version'])} &middot; sha256 <code>{e(b['hashes']['rulepack_sha256'][:16])}</code> &middot; engine {e(b['engine'])} &middot; result <code>{e(b['hashes']['result_sha256'][:16])}</code></p>
<h2>Findings</h2><table><tr><th>Rule</th><th>Status</th><th>What was found</th><th>Source</th></tr>{''.join(rows)}</table>
<h2>Live regulator intelligence</h2>{live_html}
<h2>Models</h2><table><tr><th>Role</th><th>Model</th><th>Provider</th><th>Purpose</th><th>Latency</th></tr>{models}</table>
<h2>Professional review</h2><div class="sign"><div></div><div></div></div><p class="muted">Pharmacist name and signature &middot; decision and time</p>
<p class="muted">{e(b['disclaimer'])}</p>
</body></html>"""


def _esc(s: Any) -> str:
    return _html.escape(str(s if s is not None else ""))
