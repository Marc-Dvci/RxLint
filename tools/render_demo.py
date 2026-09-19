"""Render the demo library to fixtures/demo_cases/<id>/{rx.jpg,label.jpg,case.json}."""
import json
from dataclasses import asdict
from pathlib import Path

from rxlint.bench.render import bottle_photo, document_photo, render_label, render_prescription
from rxlint.demo import CASES

OUT = Path(__file__).resolve().parents[1] / "fixtures" / "demo_cases"

for c in CASES:
    d = OUT / c.id
    d.mkdir(parents=True, exist_ok=True)
    seed = c.rx.seed
    rx = document_photo(render_prescription(c.rx), seed=seed)
    lab = bottle_photo(render_label(c.label), seed=seed + 1)
    for scene, name in ((rx, "rx"), (lab, "label")):
        img = scene.image
        if max(img.size) > 1600:
            r = 1600 / max(img.size)
            img = img.resize((int(img.width * r), int(img.height * r)))
        img.save(d / f"{name}.jpg", quality=90)
    meta = {**c.meta(), "gold": {"rx": rx.gold(), "label": lab.gold()}}
    (d / "case.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8", newline="\n")
    print(c.id, c.title)
