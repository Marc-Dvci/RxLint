"""Write the photo brief for the demo library and export print-ready flat labels and prescriptions.

    python tools/image_prompts.py --out "../01_IMAGE_PROMPTS.md" --print-dir fixtures/print

The prompts are generated from src/rxlint/demo.py, so the text in each image matches the facts the
rules expect (strength, dose, lot, expiry) character for character.
"""

import argparse
from pathlib import Path

from rxlint.bench.render import render_label, render_prescription
from rxlint.demo import CASES

STYLE_BOTTLE = (
    "Photorealistic smartphone photo taken by a pharmacist at a pharmacy counter: a {size} amber plastic pharmacy bottle "
    "of {form_short} with a white child-resistant ridged cap, standing on a light grey laminate counter, soft overhead "
    "fluorescent light with a faint reflection on the bottle, shallow depth of field, slight natural camera angle of about "
    "10 degrees, a blurred dispensing tray in the background. The bottle carries a white printed pharmaceutical label with a "
    "{accent} header band. The label text is sharp, flat-printed, perfectly legible and exactly as follows (keep line breaks, "
    "spelling, numbers and units exactly; no other text on the label):"
)
STYLE_RX = (
    "Photorealistic top-down smartphone photo of a paper prescription lying on a wooden desk, natural window light from the "
    "left, a slight shadow at the paper edge, paper slightly curved, the whole sheet in frame. The prescription is a clinic "
    "prescription form with a {header} letterhead and ruled lines. {writing} All text is legible and exactly as follows "
    "(keep spelling, numbers and units exactly; no other text):"
)
ACCENT = {(176, 38, 58): "deep red", (30, 90, 170): "blue", (20, 120, 90): "green", (120, 60, 150): "purple",
          (200, 110, 20): "orange", (70, 70, 80): "dark grey"}


def bottle_text(lab) -> list[str]:
    lines = ["Rx only", lab.generic, lab.form, lab.strength, lab.volume, lab.lot, lab.expiry]
    if lab.manufacturer:
        lines.append(f"Manufactured by {lab.manufacturer}")
    lines.append(lab.band)
    if lab.injection:
        lines.append(f"(small grey print near the bottom edge) {lab.injection}")
    return lines


def rx_text(rx) -> list[str]:
    fr = rx.language == "fr"
    lines = [rx.clinic, rx.clinic_line, f"Patient: {rx.patient.split(': ', 1)[-1]}", f"{'Âge' if fr else 'Age'}: {rx.age}"]
    if rx.weight:
        lines.append(f"{'Poids' if fr else 'Weight'}: {rx.weight}")
    if rx.allergies:
        lines.append(f"Allergies: {rx.allergies}")
    lines += [f"Date: {rx.date}", f"Rx {rx.drug}"]
    if rx.strength:
        lines.append(rx.strength)
    dose = rx.dose if not rx.ambiguous_dose else rx.ambiguous_dose[0]
    lines.append(f"{'Posologie' if fr else 'Sig'}: {dose} {rx.frequency}")
    lines.append(f"{'pendant' if fr else 'for'} {rx.duration}")
    if rx.indication:
        lines.append(f"Indication: {rx.indication}")
    lines.append(f"{'Prescripteur' if fr else 'Prescriber'}: {rx.prescriber} (with a handwritten signature)")
    if rx.injection:
        lines.append(f"(small print in the margin) {rx.injection}")
    return lines


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--print-dir", required=True)
    args = ap.parse_args()
    pd = Path(args.print_dir)
    pd.mkdir(parents=True, exist_ok=True)
    md: list[str] = []
    md.append("# Photo brief for the RxLint demo library\n")
    md.append("Each demo case needs two photos: the prescription (`rx.jpg`) and the medicine bottle (`label.jpg`). "
              "The text in each photo must match the text below exactly, because the rules check those values.\n")
    md.append("## Two ways to make the photos\n")
    md.append("**A. Print and photograph (most reliable).** `fixtures/print/` holds a print-ready label and prescription for every "
              "case. Print each label at 90 x 49 mm on white label paper, stick it on an empty amber 100 mL pharmacy bottle, "
              "print the prescription on A5 paper, and photograph both with a phone under normal indoor light. The text is exact "
              "and the photos are real.\n")
    md.append("**B. Generate with an image model.** Use a model that renders text reliably (for example GPT Image, Imagen 4, "
              "Ideogram 3 or FLUX.1 Kontext). Generate at 1536 x 2048 (portrait) for prescriptions and 2048 x 2048 for bottles. "
              "Zoom into every generated image and compare each line with the list below; regenerate if any character differs, "
              "because a single wrong digit changes the verdict. Keep all names fictional and do not add real brand logos.\n")
    md.append("## After making the photos\n")
    md.append("1. Save them as `fixtures/demo_cases/<ID>/rx.jpg` and `fixtures/demo_cases/<ID>/label.jpg` (JPEG, longest side at most 2000 px).\n"
              "2. Tell Claude the photos are in place. The demo cases are re-run through Token Factory with `RXLINT_MODEL_MODE=record python tools/run_demo.py`, "
              "which records the model responses and checks every verdict against the expected one.\n"
              "3. The benchmark keeps using rendered images, because it needs pixel-exact ground truth.\n")
    for c in CASES:
        rx, lab = c.rx, c.label
        md.append(f"\n## Case {c.id}: {c.title}\n")
        md.append(f"*{c.summary}* Expected verdict: **{c.expect}**.\n")
        size = "100 mL" if "100" in lab.volume else lab.volume.split(" ")[0] + " mL" if "mL" in lab.volume else "100 mL"
        form = "oral suspension" if "Suspension" in lab.form or "suspension" in lab.form else "tablets"
        md.append(f"### Bottle (`fixtures/demo_cases/{c.id}/label.jpg`)\n")
        md.append("```text\n" + STYLE_BOTTLE.format(size=size, form_short=form, accent=ACCENT.get(tuple(lab.accent), "coloured")) + "\n\n"
                  + "\n".join(bottle_text(lab)) + "\n```\n")
        md.append(f"### Prescription (`fixtures/demo_cases/{c.id}/rx.jpg`)\n")
        if rx.ambiguous_dose:
            writing = (f"The prescription is handwritten in blue ballpoint pen. The dose was first written as {rx.ambiguous_dose[0]} and then "
                       f"overwritten with {rx.ambiguous_dose[1]} in the same place, so the first digit of the dose is genuinely ambiguous "
                       "between the two readings; the rest of the handwriting is neat.")
        elif rx.handwritten:
            writing = "The values are handwritten in blue ballpoint pen in neat cursive; the field labels are printed."
        else:
            writing = "The values are typed in a clean sans-serif font."
        header = "green" if "Riverside" in rx.clinic else "neutral"
        md.append("```text\n" + STYLE_RX.format(header=header, writing=writing) + "\n\n" + "\n".join(rx_text(rx)) + "\n```\n")
        render_label(lab).image.save(pd / f"{c.id}_label.png", dpi=(330, 330))
        render_prescription(rx).image.save(pd / f"{c.id}_prescription.png", dpi=(220, 220))
    Path(args.out).write_text("\n".join(md), encoding="utf-8")
    print(f"wrote {args.out} and {len(CASES) * 2} print files to {pd}")


if __name__ == "__main__":
    main()
