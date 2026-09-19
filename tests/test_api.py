"""HTTP entry points, driven the way the web app calls them. Model responses come from the recorded cassette."""
import importlib
import os
import time

import pytest


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    os.environ["RXLINT_MODEL_MODE"] = "replay"
    os.environ["RXLINT_LOAD_DOTENV"] = "0"
    os.environ["RXLINT_DEMO_PHOTOS"] = "renders"
    os.environ["RXLINT_DATA"] = str(tmp_path_factory.mktemp("data"))
    os.environ.pop("TAVILY_API_KEY", None)
    from fastapi.testclient import TestClient

    import rxlint.api.app as app_mod

    importlib.reload(app_mod)
    return TestClient(app_mod.app)


def run_demo(client, demo_id):
    r = client.post("/api/cases", data={"demo_id": demo_id})
    assert r.status_code == 200
    cid = r.json()["case_id"]
    for _ in range(240):
        body = client.get(f"/api/cases/{cid}").json()
        if body["status"] == "done":
            return cid, body
        time.sleep(0.25)
    raise AssertionError("case did not finish")


def test_health(client):
    h = client.get("/api/health").json()
    assert h["rulepack"]["rules"] == 59
    assert set(h["languages"]) == {"en", "fr", "ar", "sw"}


def test_demo_a_end_to_end(client):
    cid, body = run_demo(client, "A")
    v = body["result"]["verification"]
    assert v["state"] == "REVIEW"
    assert v["findings"][0]["rule_id"] == "RX-PRODUCT-003"
    assert all(c["replayed"] for c in body["result"]["model_calls"])
    report = client.get(f"/api/cases/{cid}/report")
    assert report.status_code == 200 and "RX-PRODUCT-003" in report.text
    bundle = client.get(f"/api/cases/{cid}/report?format=json").json()
    assert bundle["hashes"]["result_sha256"] == v["result_sha256"]


def test_confirmation_flow_on_ambiguous_dose(client):
    cid, body = run_demo(client, "D")
    assert body["result"]["verification"]["state"] == "CANNOT_VERIFY"
    assert "rx.dose" in body["result"]["clarification"]["fields"]
    after = client.post(f"/api/cases/{cid}/confirm", json={"confirmations": {"rx.dose": "7.5 mL"}}).json()
    assert after["verification"]["state"] == "PASS"
    node = after["verification"]["evidence"]["ev_rx_dose"]
    assert "confirmed by the pharmacist" in node["notes"][0]
    under = client.post(f"/api/cases/{cid}/confirm", json={"confirmations": {"rx.dose": "2.5 mL"}}).json()
    assert under["verification"]["state"] == "REVIEW"


def test_explanations_carry_the_locked_values(client):
    cid, _ = run_demo(client, "A")
    for lang in ("en", "ar"):
        e = client.post(f"/api/cases/{cid}/explain", json={"language": lang, "audience": "caregiver"}).json()
        assert e["source"] in ("model", "deterministic")
        assert "250 mg / 62.5 mg per 5 mL" in e["text"] or "250" in e["text"]
        assert e["action"] in e["text"]
    assert client.post(f"/api/cases/{cid}/explain", json={"language": "de", "audience": "caregiver"}).status_code == 400


def test_rulepack_endpoint_reports_verified_quotes(client):
    p = client.get("/api/rulepack").json()
    assert p["quotes_verified"] == p["quotes_checked"] >= 70


def test_manual_verify(client):
    from conftest import HERO

    r = client.post("/api/verify", json={"fields": HERO, "dispense_date": "2026-09-19"}).json()
    assert r["state"] == "PASS"


def test_path_traversal_is_rejected(client):
    for url in ("/..%2F..%2Fsrc%2Frxlint%2Fdemo.py", "/%2e%2e/%2e%2e/pyproject.toml", "/..%5C..%5Cpyproject.toml"):
        r = client.get(url)
        assert "Case G carries" not in r.text and "[project]" not in r.text, url
    assert client.get("/api/demo-cases/A/..%2Fcase.json").status_code == 404
    assert client.get("/api/does-not-exist").status_code == 404
    assert client.get("/api/cases/..%2F..%2Fetc").status_code in (400, 404)
