/**
 * RxLint demo tour: drives the real web app with a drawn cursor and a caption bar.
 *
 * Injected by record.py into the running app. Every wait is on the page clock, so under a
 * virtual clock the choreography advances exactly one frame interval per rendered frame.
 * Visual beats are cued to the measured start of the sentence they belong to (timing.json),
 * captions change on the same clock, and every failed element lookup is counted so a beat
 * that silently points at nothing fails the render instead of reading as a pause.
 */
(function () {
  'use strict';
  const T = { failures: [], done: false, timing: null, t0: 0, log: [] };
  window.RxTour = T;

  // ── overlay ───────────────────────────────────────────────────────────────
  const style = document.createElement('style');
  style.textContent = `
    #rx-cursor { position: fixed; left: 0; top: 0; width: 26px; height: 32px; z-index: 100000; pointer-events: none;
      opacity: 0; transition: opacity 240ms ease; filter: drop-shadow(0 2px 3px rgba(0,0,0,.35)); }
    #rx-cursor.on { opacity: 1; }
    #rx-ripple { position: fixed; width: 34px; height: 34px; border-radius: 50%; z-index: 99999; pointer-events: none;
      border: 2.5px solid #2f6feb; background: rgba(47,111,235,.18); opacity: 0; transform: translate(-50%,-50%) scale(.4); }
    #rx-ripple.go { animation: rxRipple 420ms ease-out forwards; }
    @keyframes rxRipple { 0% { opacity: .9; transform: translate(-50%,-50%) scale(.4); } 100% { opacity: 0; transform: translate(-50%,-50%) scale(1.5); } }
    #rx-caption { position: fixed; left: 50%; bottom: 34px; transform: translateX(-50%) translateY(14px); z-index: 100001;
      max-width: 72%; padding: 13px 22px; border-radius: 14px; background: rgba(17,24,39,.92); color: #fff;
      font: 500 21px/1.35 Inter, Roboto, system-ui, sans-serif; letter-spacing: .1px; text-align: center;
      box-shadow: 0 10px 30px rgba(0,0,0,.35); opacity: 0; transition: opacity 260ms ease, transform 260ms ease; pointer-events: none; }
    #rx-caption.on { opacity: 1; transform: translateX(-50%) translateY(0); }
    #rx-caption b { color: #9ec5ff; font-weight: 600; }
    html { scroll-behavior: auto !important; }
    * { caret-color: transparent; }
    .grid4:not(.rx-outcome-metrics):has(> .card.metric) { grid-template-columns: repeat(3, minmax(0, 1fr)); }
    .grid4:not(.rx-outcome-metrics) > .card.metric:nth-child(2) { display: none; }
    .page:has(.grid4 > .card.metric) table.tbl:has(thead th:nth-child(8)):not(:has(thead th:nth-child(9))) :is(th, td):nth-child(7) { display: none; }
  `;
  document.head.appendChild(style);
  const cursor = document.createElement('div');
  cursor.id = 'rx-cursor';
  cursor.innerHTML = '<svg viewBox="0 0 26 32" width="26" height="32"><path d="M3 2 L3 24 L8.6 18.8 L12.6 28 L16.4 26.4 L12.5 17.4 L20 17.4 Z" fill="#fff" stroke="#111" stroke-width="1.6" stroke-linejoin="round"/></svg>';
  const ripple = document.createElement('div');
  ripple.id = 'rx-ripple';
  const caption = document.createElement('div');
  caption.id = 'rx-caption';
  document.body.append(cursor, ripple, caption);

  let cx = -100, cy = -100;
  const setCursor = (x, y) => { cx = x; cy = y; cursor.style.transform = `translate(${x - 3}px, ${y - 2}px)`; };
  setCursor(-100, -100);

  // ── clock and waits ───────────────────────────────────────────────────────
  const now = () => performance.now() - T.t0;
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const nextFrame = () => new Promise((r) => requestAnimationFrame(() => r()));
  const ease = (t) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);

  async function untilTime(ms) {
    while (now() < ms) await sleep(20);
  }
  function sentence(sec, i) {
    const s = T.timing.sections.find((x) => x.id === sec);
    return s.sentences[i];
  }
  /** Wait until ``lead`` ms before sentence ``i`` of section ``sec`` starts. */
  async function cue(sec, i, lead = 350) {
    await untilTime(sentence(sec, i).start_ms - lead);
  }
  async function waitFor(fn, label, timeout = 60000) {
    const start = now();
    for (;;) {
      let v = null;
      try { v = fn(); } catch (e) { v = null; }
      if (v) return v;
      if (now() - start > timeout) { T.failures.push(`timeout: ${label}`); return null; }
      await sleep(40);
    }
  }

  // ── lookups ───────────────────────────────────────────────────────────────
  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
  const byText = (sel, text, root = document) => $$(sel, root).find((el) => (el.textContent || '').trim().includes(text)) || null;
  function need(el, label) {
    if (!el) { T.failures.push(`missing: ${label}`); T.log.push(`${(now() / 1000).toFixed(1)}s missing ${label}`); }
    return el;
  }

  // ── motion ────────────────────────────────────────────────────────────────
  async function animate(ms, step) {
    const t0 = now();
    for (;;) {
      const p = Math.min(1, (now() - t0) / ms);
      step(ease(p));
      if (p >= 1) return;
      await nextFrame();
    }
  }
  const TOP = 135; // sticky top bar (zoomed)
  async function scrollTo(y, ms = 650) {
    const from = window.scrollY;
    const max = Math.max(0, document.documentElement.scrollHeight - window.innerHeight);
    const to = Math.max(0, Math.min(max, y));
    if (Math.abs(to - from) < 2) return;
    await animate(ms, (p) => window.scrollTo(0, from + (to - from) * p));
  }
  /** Scroll so ``el`` sits ``frac`` of the way down the viewport (0 = just under the top bar). */
  async function reveal(el, frac = 0.25, ms = 650) {
    if (!el) return;
    const r = el.getBoundingClientRect();
    const target = window.scrollY + r.top - TOP - (window.innerHeight - TOP - r.height) * frac;
    await scrollTo(target, ms);
  }
  async function moveTo(el, opts = {}) {
    if (!el) return;
    const { dx = 0, dy = 0, ms = 520, ax = 0.5, ay = 0.5 } = opts;
    cursor.classList.add('on');
    const r = el.getBoundingClientRect();
    const tx = r.left + r.width * ax + dx, ty = r.top + r.height * ay + dy;
    const sx = cx < 0 ? tx + 180 : cx, sy = cy < 0 ? ty + 120 : cy;
    await animate(ms, (p) => setCursor(sx + (tx - sx) * p, sy + (ty - sy) * p));
  }
  async function press() {
    ripple.style.left = `${cx}px`; ripple.style.top = `${cy}px`;
    ripple.classList.remove('go'); void ripple.offsetWidth; ripple.classList.add('go');
    await sleep(140);
  }
  async function click(el, opts = {}) {
    if (!need(el, opts.label || 'click target')) return;
    await moveTo(el, opts);
    await sleep(opts.settle ?? 160);
    await press();
    el.click();
    await sleep(120);
  }
  async function hover(el, opts = {}) {
    if (!need(el, opts.label || 'hover target')) return;
    await moveTo(el, opts);
  }
  /** A slow drift along a list of elements, one per ``each`` ms. */
  async function sweep(els, each = 900, opts = {}) {
    for (const el of els) { await moveTo(el, { ...opts, ms: each * 0.55 }); await sleep(each * 0.45); }
  }

  // ── captions ──────────────────────────────────────────────────────────────
  function setCaption(text) {
    if (!text) { caption.classList.remove('on'); return; }
    caption.innerHTML = text;
    caption.classList.add('on');
  }
  async function captionLoop() {
    const beats = [];
    for (const s of T.timing.sections) for (const x of s.sentences) if (x.cap) beats.push({ at: x.start_ms, cap: x.cap });
    for (const b of beats) { await untilTime(b.at); setCaption(b.cap); }
  }

  // ── app helpers ───────────────────────────────────────────────────────────
  const home = async () => { window.location.hash = '#/'; await waitFor(() => $('.demo'), 'home cards'); };
  const demoCard = (id) => $$('.demo').find((c) => ($('.id', c)?.textContent || '').trim() === id) || null;
  async function openDemo(id) {
    await home();
    await sleep(80);
    const card = need(demoCard(id), `demo card ${id}`);
    await click(card, { ay: 0.35 });
    await waitFor(() => $('.page-head h1') && ($('.page-head h1').textContent || '').startsWith(id + ' '), `case page ${id}`, 20000);
    window.scrollTo(0, 0);
    await waitFor(() => $('.verdict'), `verdict of ${id}`, 120000);
    window.scrollTo(0, 0);
    await sleep(60);
  }
  const factRow = (label) => $$('table.facts tbody tr').find((tr) => (tr.children[0]?.textContent || '').trim() === label) || null;
  const step = (i) => $$('.pipeline .step')[i] || null;
  /** A highlight rectangle as a screen-space target. SVG geometry ignores the root zoom, so the
   *  box is placed from its normalised attributes over the image it annotates. */
  function boxTarget(rect) {
    if (!rect) return null;
    const svg = rect.ownerSVGElement;
    if (!svg) return null;
    const r = svg.getBoundingClientRect();
    const x = parseFloat(rect.getAttribute('x')), y = parseFloat(rect.getAttribute('y'));
    const w = parseFloat(rect.getAttribute('width')), h = parseFloat(rect.getAttribute('height'));
    return { getBoundingClientRect: () => ({ left: r.left + x * r.width, top: r.top + y * r.height, width: w * r.width, height: h * r.height }) };
  }
  const sect = (upper) => $$('.finding .body .sect').find((s) => ($('.upper', s)?.textContent || '').trim() === upper) || null;

  // ── sections ──────────────────────────────────────────────────────────────
  async function secHome() {
    // Establish the product and workflow before pointing at the example.
    await cue('home', 0);
    await sleep(600);
    await hover($('.page-head h1'), { ay: 0.5, ms: 900, label: 'product purpose' });
    await cue('home', 1);
    await hover($('.page-head p'), { ay: 0.5, ms: 700, label: 'evidence-linked checks' });
    await cue('home', 2);
    await hover(demoCard('A'), { ay: 0.3, ms: 900, label: 'card A' });
    await cue('home', 3);
    await hover(demoCard('A'), { ay: 0.85, ms: 700, label: 'card A text' });
  }

  async function secRead() {
    await cue('read', 0, 900);
    await openDemo('A');
    await cue('read', 1);
    await hover(step(1), { label: 'pipeline step 2' });
    await sleep(1400);
    // The photo viewer: hover each image.
    const imgs = $$('.viewer img');
    await reveal($('.viewer-tabs'), 0.05, 700);
    if (imgs.length >= 2) { await hover(imgs[0], { ms: 700 }); await sleep(900); await hover(imgs[1], { ms: 700 }); }
    await cue('read', 2);
    await reveal($('table.facts'), 0.0, 700);
    await hover(factRow('Prescribed medicine'), { ax: 0.8, label: 'fact row prescribed medicine' });
    await sleep(900);
    await hover(factRow('Prescribed strength'), { ax: 0.8, label: 'fact row prescribed strength' });
    await cue('read', 3);
    await scrollTo(0, 650);
    await hover(step(3), { label: 'pipeline step 4' });
    await cue('read', 4);
    await reveal($('.viewer-tabs'), 0.02, 650);
    await click(factRow('Prescribed strength'), { ax: 0.3, label: 'fact row prescribed strength' });
    await sleep(200);
    const hot = await waitFor(() => $('.viewer svg.boxes rect.box.hot'), 'highlight box', 4000);
    await hover(boxTarget(hot), { ms: 700, ax: 0.6, ay: 0.7, label: 'highlight' });
  }

  async function secFinding() {
    await cue('finding', 0);
    await scrollTo(0, 600);
    await hover($('.verdict .state'), { label: 'verdict' });
    await cue('finding', 1);
    const card = need($('.finding.fail'), 'critical finding');
    await reveal(card, 0.02, 700);
    await hover(sect('Observed'), { ax: 0.55, label: 'observed' });
    await cue('finding', 2);
    await hover(sect('Calculation'), { ax: 0.5, ay: 0.35, label: 'calculation' });
    await sleep(1600);
    await hover(sect('Calculation'), { ax: 0.5, ay: 0.8, ms: 600, label: 'calculation 2' });
    await cue('finding', 3);
    await reveal(sect('Rule source'), 0.35, 650);
    await hover(sect('Rule source'), { ax: 0.4, ay: 0.4, label: 'rule source' });
    await sleep(1800);
    await reveal($('.viewer-tabs'), 0.02, 700);
    const boxes = $$('.viewer svg.boxes rect.box.hot').map(boxTarget).filter(Boolean);
    if (boxes.length) await sweep(boxes.slice(0, 2), 1100, { ax: 0.6, ay: 0.7 });
  }

  async function secExplain() {
    await cue('explain', 0, 1200);
    const panel = need(byText('.card', 'Explanation'), 'explanation card');
    await reveal(panel, 0.1, 750);
    await cue('explain', 0, -200);
    await click(byText('.explain .seg button', 'Français', panel), { label: 'Français' });
    await waitFor(() => (($('.explain .text', panel)?.getAttribute('lang')) === 'fr'), 'french text', 20000);
    await sleep(2000);
    await click(byText('.explain .seg button', 'العربية', panel), { label: 'Arabic' });
    await waitFor(() => (($('.explain .text', panel)?.getAttribute('lang')) === 'ar'), 'arabic text', 20000);
    await cue('explain', 1);
    await hover($('.explain .text', panel), { ax: 0.5, ay: 0.4, label: 'explanation text' });
    await cue('explain', 2);
    await hover(byText('.badge', 'integrity checked', panel), { label: 'integrity badge' });
    await sleep(2200);
    await hover(byText('.explain .seg button', 'English', panel), { ms: 500, label: 'English' });
  }

  async function secHandwriting() {
    await cue('handwriting', 0, 2600);
    await openDemo('D');
    await cue('handwriting', 0, 0);
    await hover($('.verdict .state'), { label: 'verdict D' });
    await sleep(900);
    const confirm = need($('.confirm'), 'confirm panel');
    await reveal(confirm, 0.1, 650);
    await hover($('.confirm .crop'), { ms: 700, label: 'crop' });
    await cue('handwriting', 1);
    await hover($('.confirm .upper'), { ax: 0.3, label: 'clarification action' });
    await sleep(1500);
    await hover($('.confirm .tiny'), { ax: 0.25, ms: 500, label: 'chosen by' });
    await cue('handwriting', 2);
    const quick = $$('.confirm .quick button').find((b) => b.textContent.includes('7.5')) || $('.confirm .quick button');
    await click(quick, { label: 'use 7.5 mL' });
    await sleep(700);
    await click(byText('.confirm button', 'Confirm reviewed values and re-check'), { label: 'confirm reviewed values and re-check' });
    await waitFor(() => (($('.verdict .state')?.textContent || '').includes('PASS')), 'D passes', 30000);
    await cue('handwriting', 3);
    await scrollTo(0, 600);
    await hover($('.verdict .state'), { label: 'verdict D pass' });
  }

  async function secLive() {
    await cue('live', 0, 2600);
    await openDemo('I');
    await cue('live', 0, 0);
    await hover($('.verdict .hashes'), { ax: 0.7, ay: 0.2, label: 'hashes' });
    await sleep(2200);
    const live = need($('.live-card'), 'live card');
    await reveal(live, 0.05, 800);
    await cue('live', 1);
    await click(byText('.live-card button', 'Run live check'), { label: 'run live check' });
    await waitFor(() => $('.notice.applicable'), 'applicable notice', 30000);
    await sleep(300);
    await reveal($('.live-card .searches'), 0.6, 700);
    const searches = $$('.live-card .searches > *').slice(0, 4);
    if (searches.length) await sweep(searches, 700, { ax: 0.2 });
    await cue('live', 2);
    await reveal($('.notice.applicable'), 0.15, 650);
    await hover(byText('.notice.applicable .badge', 'lot'), { label: 'lot badge' });
    await sleep(1400);
    await hover($('.notice.applicable .snip'), { ax: 0.4, ay: 0.4, ms: 600, label: 'snippet' });
    await cue('live', 3);
    await hover($('.live-card .sub'), { ax: 0.15, label: 'live subtitle' });
  }

  async function secBench() {
    await cue('bench', 0, 1400);
    window.location.hash = '#/bench';
    await waitFor(() => $('.card.metric'), 'bench tiles', 20000);
    window.scrollTo(0, 0);
    await sleep(100);
    // Feature reading accuracy and verdict outcomes in the filmed summary.
    // Detailed evaluation data remains available in the app and frozen report.
    const reviewTile = need($$('.card.metric').find((el) => (el.textContent || '').includes('cases needing confirmation')), 'review metric');
    const metricGrid = reviewTile?.parentElement;
    reviewTile?.remove();
    if (metricGrid) {
      metricGrid.classList.add('rx-outcome-metrics');
      metricGrid.style.gridTemplateColumns = 'repeat(3, minmax(0, 1fr))';
    }
    for (const table of $$('table.tbl')) {
      const headers = $$('thead th', table);
      const reviewColumn = headers.findIndex((el) => (el.textContent || '').trim() === 'Asked to confirm');
      if (reviewColumn >= 0) for (const row of $$('tr', table)) row.children[reviewColumn]?.remove();
    }
    const tiles = $$('.card.metric');
    await cue('bench', 0, 0);
    await hover(tiles[0], { ay: 0.4, label: 'tile 0' });
    await cue('bench', 1);
    const strength = need(byText('table.tbl tbody tr', 'dispensed.strength'), 'label strength result');
    await reveal(strength, 0.3, 600);
    await hover(strength, { ax: 0.8, label: 'label strength accuracy' });
    await cue('bench', 2);
    await scrollTo(0, 450);
    await hover(tiles[1], { ay: 0.4, label: 'exact verdict tile' });
    await sleep(1400);
    await hover(tiles[2], { ay: 0.4, label: 'overwritten dose tile' });
    await sleep(1400);
    const row = byText('table.tbl tbody tr', 'reliability head');
    await reveal(row, 0.3, 600);
    await hover(row, { ax: 0.15, label: 'rxlint row' });
  }

  async function secClose() {
    await cue('close', 0, 1200);
    window.location.hash = '#/about';
    await waitFor(() => byText('h2', 'may and may not'), 'about table', 20000);
    window.scrollTo(0, 0);
    await sleep(100);
    const table = need(byText('h2', 'may and may not')?.parentElement, 'may table');
    await reveal(table, 0.0, 750);
    const rows = $$('tr', table);
    await cue('close', 0, 0);
    await sweep(rows.slice(0, 4), 1050, { ax: 0.12 });
    await cue('close', 1);
    await sweep(rows.slice(4), 1000, { ax: 0.12 });
    await cue('close', 2, 700);
    await home();
    window.scrollTo(0, 0);
    await sleep(200);
    const chips = $$('.topbar .chip');
    if (chips.length) await sweep(chips.slice(0, 3), 1300, { ay: 0.5 });
    cursor.classList.remove('on');
  }

  // ── orchestrator ──────────────────────────────────────────────────────────
  T.start = async function (timing) {
    T.timing = timing;
    T.t0 = performance.now();
    captionLoop();
    const run = async (name, fn) => {
      try { await fn(); } catch (e) { T.failures.push(`${name}: ${e && e.message ? e.message : e}`); }
      T.log.push(`${(now() / 1000).toFixed(1)}s end ${name}`);
    };
    await run('home', secHome);
    await run('read', secRead);
    await run('finding', secFinding);
    await run('explain', secExplain);
    await run('handwriting', secHandwriting);
    await run('live', secLive);
    await run('bench', secBench);
    await run('close', secClose);
    T.done = true;
  };
})();
