"""Render the RxLint demo as an MP4, one frame at a time, on a virtual clock.

Playwright opens the real web app served by a local RxLint server, injects tour.js and hands it
the narration timing. Chromium's BeginFrame control then advances every timer, transition and
animation by exactly one frame interval per frame and returns each frame as a lossless PNG,
which ffmpeg encodes together with narration.wav.

    (from the repository root, run a replay-mode server on port 8011)
    python docs/demo/narrate.py
    python docs/demo/record.py [--seconds 40] [--stills] [--probe]

Output: rxlint-demo.mp4, 1920x1080 at 30 fps, H.264 + AAC.
"""

from __future__ import annotations

import base64
import json
import pathlib
import subprocess
import sys
import threading
import time

from playwright.sync_api import sync_playwright

HERE = pathlib.Path(__file__).resolve().parent
FRAMES = HERE / "frames"
BASE = "http://127.0.0.1:8011"
VIEWPORT = (1920, 1080)
ZOOM = 1.2           # the app root is zoomed, so the page reads like a 1600x900 layout rasterised at 1080p
FRAME = (1920, 1080)
FPS = 30
STILLS = "--stills" in sys.argv
PROBE = "--probe" in sys.argv
PREVIEW = float(sys.argv[sys.argv.index("--seconds") + 1]) if "--seconds" in sys.argv else None

CHROMIUM_ARGS = [
    "--enable-begin-frame-control",
    "--run-all-compositor-stages-before-draw",
    "--disable-new-content-rendering-timeout",
    "--disable-threaded-animation",
    "--disable-threaded-scrolling",
    "--disable-checker-imaging",
    "--force-color-profile=srgb",
    "--hide-scrollbars",
    "--font-render-hinting=none",
]


def encoder(out: pathlib.Path, narration: pathlib.Path, seconds: float, total_ms: int) -> subprocess.Popen:
    return subprocess.Popen(
        ["ffmpeg", "-y", "-loglevel", "error",
         "-f", "image2pipe", "-framerate", str(FPS), "-i", "-",
         "-i", str(narration),
         "-filter_complex",
         f"[0:v]scale={FRAME[0]}:{FRAME[1]}:flags=lanczos,fade=t=in:st=0:d=0.4,fade=t=out:st={seconds - 0.7:.2f}:d=0.7[v];"
         f"[1:a]apad,atrim=0:{seconds:.3f},afade=t=out:st={total_ms / 1000 - 0.5:.2f}:d=0.5[a]",
         "-map", "[v]", "-map", "[a]",
         "-c:v", "libx264", "-preset", "slow", "-crf", "18", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-b:a", "192k", "-t", f"{seconds:.2f}", "-movflags", "+faststart", str(out)],
        stdin=subprocess.PIPE, stderr=subprocess.PIPE)


def warm_up() -> None:
    """Run the film's cases once so the server's readers and OCR models are loaded before the clock starts."""
    import urllib.request

    CRLF = chr(13) + chr(10)
    for cid in ("A", "D", "I"):
        body = ("--x" + CRLF + 'Content-Disposition: form-data; name="demo_id"' + CRLF + CRLF + cid + CRLF + "--x--" + CRLF).encode()
        req = urllib.request.Request(BASE + "/api/cases", data=body, headers={"Content-Type": "multipart/form-data; boundary=x"})
        case_id = json.loads(urllib.request.urlopen(req).read())["case_id"]
        t0 = time.time()
        while time.time() - t0 < 300:
            env = json.loads(urllib.request.urlopen(BASE + f"/api/cases/{case_id}").read())
            if env.get("status") in ("done", "error"):
                break
            time.sleep(0.5)
        print(f"  warm-up {cid}: {env.get('status')} in {time.time() - t0:.1f}s")


def main() -> None:
    warm_up()
    timing = json.loads((HERE / "timing.json").read_text(encoding="utf-8"))
    total_ms = timing["total_ms"]
    narration = HERE / "narration.wav"
    live_g = json.loads((HERE / "live_I.json").read_text(encoding="utf-8"))
    tour = (HERE / "tour.js").read_text(encoding="utf-8")
    seconds = min(total_ms / 1000, PREVIEW or 1e9)
    frames = int(round(seconds * FPS))
    interval = 1000 / FPS
    out = HERE / ("preview.mp4" if PREVIEW else "rxlint-demo.mp4")
    sentence_at = sorted((s["start_ms"], f"{sec['id']}-{i}") for sec in timing["sections"] for i, s in enumerate(sec["sentences"]))
    still_at: dict[int, str] = {}
    for start, name in sentence_at:
        for k, off in (("a", 500), ("b", 1700)):
            still_at[int(round((start + off) / interval))] = f"{name}{k}"
    if STILLS:
        FRAMES.mkdir(exist_ok=True)
        for old in FRAMES.glob("*.png"):
            old.unlink()
    print(f"rendering {seconds:.1f}s = {frames} frames at {FPS} fps -> {out.name}")

    ff = None if PROBE else encoder(out, narration, seconds, total_ms)
    written = 0
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, args=CHROMIUM_ARGS)
        context = browser.new_context(viewport={"width": VIEWPORT[0], "height": VIEWPORT[1]}, device_scale_factor=1,
                                      color_scheme="light", locale="en-GB")
        page = context.new_page()
        page.on("pageerror", lambda e: print(f"  page error: {e}"))
        page.on("console", lambda m: print(f"  console {m.type}: {m.text}") if m.type in ("error", "warning") else None)
        # The live regulator check is served from a recorded run of the same case (a real Tavily result
        # for case I), so the film is the same every time it is rendered.
        page.route("**/api/cases/*/live", lambda route: route.fulfill(status=200, content_type="application/json",
                                                                     body=json.dumps(live_g, ensure_ascii=False)))
        page.goto(BASE + "/#/", wait_until="load", timeout=60_000)
        page.wait_for_selector(".demo img", timeout=60_000)
        page.add_style_tag(content=f"#root {{ zoom: {ZOOM}; }} .side {{ height: calc(100vh / {ZOOM}); }} "
                           ".page {{ padding-bottom: 240px; }}")
        # Under BeginFrame control no frame is produced until asked, so lazy images would never be scheduled.
        page.evaluate("() => document.querySelectorAll('img[loading=lazy]').forEach((i) => { i.loading = 'eager'; })")
        page.wait_for_function("() => [...document.querySelectorAll('.demo img')].length >= 18 && "
                               "[...document.querySelectorAll('.demo img')].every((i) => i.complete && i.naturalWidth > 0)", timeout=60_000, polling=100)
        page.wait_for_function("() => document.fonts.status === 'loaded'", timeout=30_000, polling=100)
        page.wait_for_timeout(1200)  # first layout settles
        page.add_script_tag(content=tour)
        page.wait_for_function("() => window.RxTour && window.RxTour.start", polling=100)

        cdp = context.new_cdp_session(page)
        expired = threading.Event()
        cdp.on("Emulation.virtualTimeBudgetExpired", lambda _e: expired.set())
        policy = cdp.send("Emulation.setVirtualTimePolicy", {"policy": "pause"})
        ticks = float(policy["virtualTimeTicksBase"])
        page.evaluate("(t) => { window.RxTour.start(t); }", timing)

        last: bytes | None = None
        t0 = time.time()
        for n in range(frames):
            expired.clear()
            cdp.send("Emulation.setVirtualTimePolicy", {"policy": "advance", "budget": interval})
            shot = cdp.send("HeadlessExperimental.beginFrame",
                            {"frameTimeTicks": ticks, "interval": interval, "noDisplayUpdates": False, "screenshot": {"format": "png"}})
            ticks += interval
            deadline = time.time() + 30
            while not expired.is_set() and time.time() < deadline:
                page.wait_for_timeout(2)
            if not expired.is_set():
                raise RuntimeError(f"virtual time stalled at frame {n} ({n / FPS:.1f}s)")
            if "screenshotData" in shot:
                last = base64.b64decode(shot["screenshotData"])
            if last is None:
                continue
            if PROBE:
                (HERE / "probe.png").write_bytes(last)
                print("probe frame written")
                break
            ff.stdin.write(last)
            written += 1
            if STILLS and n in still_at:
                (FRAMES / f"{still_at[n]}.png").write_bytes(last)
            if n % 300 == 0:
                print(f"  {n / FPS:6.1f}s  {(time.time() - t0) / max(n, 1) * 1000:5.0f} ms/frame")
        state = page.evaluate("() => ({done: window.RxTour.done, failures: window.RxTour.failures, log: window.RxTour.log})")
        browser.close()

    if ff is not None:
        ff.stdin.close()
        ff.wait()
        if ff.returncode:
            raise RuntimeError(f"ffmpeg failed ({ff.returncode}):\n{ff.stderr.read().decode(errors='replace')[-4000:]}")
        print(f"\n{out.name}  {written} frames  {seconds:.1f}s  {out.stat().st_size / 1e6:.1f} MB")
    print("tour done:", state["done"])
    print("\n".join("  " + l for l in state["log"]))
    if state["failures"]:
        print("FAILURES:\n" + "\n".join("  " + f for f in state["failures"]))
        sys.exit(1)


if __name__ == "__main__":
    main()
