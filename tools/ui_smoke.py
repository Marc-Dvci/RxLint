"""Drive the real web UI: open the home page, run demo cases, exercise every panel, save screenshots.

    python tools/ui_smoke.py --base http://127.0.0.1:8000 --out <dir> [--cases A D G]
"""
import argparse
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ap = argparse.ArgumentParser()
ap.add_argument("--base", default="http://127.0.0.1:8000")
ap.add_argument("--out", required=True)
ap.add_argument("--cases", nargs="*", default=["A", "D", "G", "F"])
ap.add_argument("--dark", action="store_true")
args = ap.parse_args()
out = Path(args.out)
out.mkdir(parents=True, exist_ok=True)
errors: list[str] = []

with sync_playwright() as p:
    b = p.chromium.launch()
    page = b.new_page(viewport={"width": 1440, "height": 1000}, color_scheme="dark" if args.dark else "light")
    page.on("console", lambda m: errors.append(f"console {m.type}: {m.text}") if m.type in ("error", "warning") else None)
    page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
    page.goto(args.base + "/#/")
    page.wait_for_selector(".demo")
    page.screenshot(path=str(out / "home.png"), full_page=True)
    for cid in args.cases:
        page.goto(args.base + "/#/")
        page.wait_for_selector(".demo")
        page.locator(".demo", has=page.locator(".id", has_text=cid)).first.click()
        page.wait_for_selector(".verdict", timeout=180000)
        page.wait_for_timeout(1500)
        page.screenshot(path=str(out / f"case_{cid}.png"), full_page=True)
        state = page.locator(".verdict .state").inner_text()
        print(cid, "->", state)
        # caregiver explanation in Arabic
        page.get_by_role("button", name="العربية").click()
        page.wait_for_timeout(800)
        # live check
        page.get_by_role("button", name="Run live check").click()
        page.wait_for_selector(".live-card .badge", timeout=60000)
        page.wait_for_timeout(1200)
        page.screenshot(path=str(out / f"case_{cid}_live.png"), full_page=True)
        if cid == "D":
            page.locator(".confirm .quick button").first.click()
            page.get_by_role("button", name="Confirm and re-check").click()
            page.wait_for_timeout(1500)
            page.screenshot(path=str(out / f"case_{cid}_confirmed.png"), full_page=True)
            print(cid, "after confirmation ->", page.locator(".verdict .state").inner_text())
    for route in ("rules", "bench", "about"):
        page.goto(args.base + f"/#/{route}")
        page.wait_for_timeout(1500)
        page.screenshot(path=str(out / f"{route}.png"), full_page=True)
    mobile = b.new_page(viewport={"width": 390, "height": 844})
    mobile.goto(args.base + "/#/")
    mobile.wait_for_selector(".demo")
    mobile.screenshot(path=str(out / "mobile_home.png"), full_page=True)
    b.close()

print("\n".join(errors) if errors else "no console errors")
sys.exit(1 if any("pageerror" in e for e in errors) else 0)
