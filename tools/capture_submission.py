"""Capture the running app and architecture for the submission gallery.

    python tools/capture_submission.py --base http://127.0.0.1:8011

The batch example intentionally leaves duration and weight unspecified, then reviews both.
It uses the fictional demo bottle and records no real patient data.
"""
import argparse
import json
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8011")
    args = ap.parse_args()
    out = ROOT / "docs/img"
    errors = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 1150}, color_scheme="light")
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(args.base + "/#/")
        page.wait_for_selector(".demo")
        page.get_by_role("button", name="FHIR prescription", exact=True).click()
        prescription = json.loads((ROOT / "fixtures/fhir/combination_suspension.json").read_text(encoding="utf-8"))
        prescription["dosageInstruction"][0]["timing"]["repeat"].pop("boundsDuration")
        page.get_by_label("FHIR prescription file").set_input_files({
            "name": "demo-order.json", "mimeType": "application/fhir+json",
            "buffer": json.dumps(prescription).encode(),
        })
        page.get_by_text("Imported as supplied. Verify patient context separately.", exact=True).wait_for()
        # Case A's photographed uploads are intentionally swapped; rx.jpg is the bottle.
        photo = page.request.get(args.base + "/api/demo-cases/A/rx.jpg")
        assert photo.ok
        page.locator("input[accept='image/*']").set_input_files({"name": "demo-bottle.jpg", "mimeType": "image/jpeg", "buffer": photo.body()})
        page.get_by_label("Age", exact=True).fill("14 months")
        page.get_by_label("Known allergies", exact=True).fill("none")
        page.get_by_label("Current medicines", exact=True).fill("none")
        page.get_by_label("Indication (optional)", exact=True).fill("otitis media")
        page.get_by_role("button", name="Verify", exact=True).scroll_into_view_if_needed()
        page.screenshot(path=str(out / "fhir_import.png"))
        page.get_by_role("button", name="Verify", exact=True).click()
        page.wait_for_selector(".confirm", timeout=120000)
        inputs = page.locator(".confirm input")
        assert inputs.count() == 2, inputs.count()
        for i in range(inputs.count()):
            input_ = inputs.nth(i)
            label = input_.get_attribute("aria-label") or ""
            input_.fill("9.5 kg" if "weight" in label.lower() else "5 days")
        case_id = page.url.split("/case/")[-1]
        before = page.request.get(args.base + f"/api/cases/{case_id}").json()["result"]
        calls = len(before["model_calls"])
        page.locator(".confirm").scroll_into_view_if_needed()
        page.screenshot(path=str(out / "fhir_batch.png"))
        page.get_by_role("button", name="Confirm reviewed values and re-check", exact=True).click()
        page.wait_for_selector(".verdict.review", timeout=30000)
        after = page.request.get(args.base + f"/api/cases/{case_id}").json()["result"]
        assert len(after["model_calls"]) == calls
        assert after["verification"]["state"] == "REVIEW"  # correct order, mismatched demo bottle
        page.evaluate("window.scrollTo(0, 0)")
        page.screenshot(path=str(out / "fhir_confirmed.png"))
        page.goto(args.base + "/#/bench")
        page.wait_for_selector(".card.metric")
        page.screenshot(path=str(out / "benchmark_app.png"))
        page.set_viewport_size({"width": 1600, "height": 900})
        for name in ("architecture", "benchmark"):
            page.goto((ROOT / f"docs/figures/{name}.html").as_uri())
            page.wait_for_timeout(300)
            page.locator("body").screenshot(path=str(out / f"{name}.png"))
        browser.close()
    assert not errors, errors
    print(f"Captured gallery images; two fields confirmed together, {calls} model calls unchanged.")


if __name__ == "__main__":
    main()
