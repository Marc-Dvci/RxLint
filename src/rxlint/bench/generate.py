"""RxLintBench case generator.

A gold case is a correct pediatric prescription and matching product, built from the WHO weight
bands in the installed pack. Mutations inject one known error each; the expected verdict and
failing rule family are declared by the mutation, then checked against the kernel run on the
gold facts. Every case renders to a prescription photo and a bottle photo with exact boxes.

Held-out structure: handwriting font, photo perturbation family, and product template are split
so that the test fold contains fonts, perturbations and products the reliability head never saw.
"""

from __future__ import annotations

import json
import random
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .render import (LabelSpec, RxSpec, bottle_photo, document_photo, perturb, render_label,
                     render_prescription)

PRODUCTS: dict[str, dict[str, Any]] = {
    "amoxicillin": {
        "rx": "Amoxicillin oral suspension", "label": "Amoxicillin", "form": "for Oral Suspension USP",
        "strengths": [("250 mg/5 mL", [250], 5), ("400 mg/5 mL", [400], 5), ("125 mg/5 mL", [125], 5)],
        "bands": [(3, 6, 250, 2), (6, 10, 375, 2), (10, 15, 500, 2), (15, 20, 750, 2), (20, 30, 1000, 2)],
        "indications": [("Acute otitis media", 5), ("Pharyngitis", 10), ("Community-acquired pneumonia", 5), ("Acute sinusitis", 5)],
        "accent": (30, 90, 170),
    },
    "amoxicillin+clavulanic_acid": {
        "rx": "Amoxicillin/clavulanate oral suspension", "label": "Amoxicillin and Clavulanate Potassium", "form": "for Oral Suspension USP",
        "strengths": [("400 mg/57 mg per 5 mL", [400, 57], 5), ("250 mg/62.5 mg per 5 mL", [250, 62.5], 5)],
        "bands": [(3, 6, 250, 2), (6, 10, 375, 2), (10, 15, 500, 2), (15, 20, 750, 2), (20, 30, 1000, 2)],
        "indications": [("Acute otitis media", 5), ("Acute sinusitis", 5), ("Cellulitis", 5), ("Cystitis", 5)],
        "accent": (176, 38, 58),
    },
    "cefalexin": {
        "rx": "Cefalexin oral suspension", "label": "Cephalexin", "form": "for Oral Suspension USP",
        "strengths": [("250 mg/5 mL", [250], 5), ("125 mg/5 mL", [125], 5)],
        "bands": [(3, 6, 125, 2), (6, 10, 250, 2), (10, 15, 375, 2), (15, 20, 500, 2), (20, 30, 625, 2)],
        "indications": [("Pharyngitis", 5), ("Impetigo", 5)],
        "accent": (20, 120, 90),
    },
    "sulfamethoxazole+trimethoprim": {
        "rx": "Co-trimoxazole oral suspension", "label": "Sulfamethoxazole and Trimethoprim", "form": "Oral Suspension USP",
        "strengths": [("200 mg/40 mg per 5 mL", [200, 40], 5)],
        "bands": [(6, 10, 200, 2), (10, 30, 400, 2)],
        "indications": [("Cystitis", 3)],
        "accent": (120, 60, 150),
    },
    "clarithromycin": {
        "rx": "Clarithromycin oral suspension", "label": "Clarithromycin", "form": "for Oral Suspension USP",
        "strengths": [("250 mg/5 mL", [250], 5), ("125 mg/5 mL", [125], 5)],
        "mgkg_dose": 7.5, "per_day": 2,
        "indications": [("Pharyngitis", 5)],
        "accent": (200, 110, 20),
    },
    "azithromycin": {
        "rx": "Azithromycin oral suspension", "label": "Azithromycin", "form": "for Oral Suspension USP",
        "strengths": [("200 mg/5 mL", [200], 5)],
        "mgkg_dose": 10, "per_day": 1,
        "indications": [],
        "accent": (70, 70, 80),
    },
}

FREQ_TEXT = {
    "en": {1: ["once daily", "OD", "every 24 hours"], 2: ["twice daily", "BID", "every 12 hours", "q12h"], 3: ["three times daily", "TID", "q8h"], 4: ["four times daily", "QID"]},
    "fr": {1: ["une fois par jour"], 2: ["2 fois par jour", "deux fois par jour"], 3: ["3 fois par jour"], 4: ["4 fois par jour"]},
}
DAYS_TEXT = {"en": "{d} days", "fr": "{d} jours"}
MANUFACTURERS = ["Meridian Generics Ltd.", "Northwind Pharma", "Calder Laboratories", "Aster Health Products", "Solway Medicines"]
CLINICS = [("Riverside Community Health Centre", "14 Quay Street · Outpatient Paediatrics"),
           ("Hillcrest Family Clinic", "2 Market Row · General Practice"),
           ("Centre de santé des Tilleuls", "8 rue des Écoles · Pédiatrie"),
           ("Lakeview Children's Clinic", "41 Harbour Road · Paediatrics")]
PRESCRIBERS = ["Dr A. Mensah", "Dr R. Duval", "Dr K. Osei", "Dr L. Moreau", "Dr S. Patel"]
PATIENTS = ["Child: L. Okafor", "Child: M. Haddad", "Child: T. Nguyen", "Enfant : J. Martin", "Child: A. Kamau"]
HAND_FONTS = ["Caveat.ttf", "ReenieBeanie.ttf", "NanumPenScript.ttf"]

MUTATIONS = {
    # name: (expected state, expected rule id prefix or None)
    "NONE": ("PASS", None),
    "STRENGTH_SWAP": ("REVIEW", "RX-PRODUCT-003"),
    "DECIMAL_SHIFT": ("REVIEW", "AWARE-"),
    "DOSE_VOLUME_CHANGE": ("REVIEW", "AWARE-"),
    "FREQUENCY_CHANGE": ("REVIEW", "AWARE-"),
    "DURATION_CHANGE": ("REVIEW", "AWARE-DUR-"),
    "DRUG_IDENTITY_SWAP": ("REVIEW", "RX-PRODUCT-001"),
    "FORMULATION_CHANGE": ("REVIEW", "RX-PRODUCT-002"),
    "ALLERGY_INSERTION": ("REVIEW", "RX-ALLERGY-"),
    "DUPLICATE_INGREDIENT": ("REVIEW", "RX-DUP-001"),
    "INTERACTION_INSERTION": ("REVIEW", "DDI-"),
    "EXPIRED_PRODUCT": ("REVIEW", "RX-PRODUCT-005"),
    "INSUFFICIENT_QUANTITY": ("REVIEW", "RX-PRODUCT-006"),
    "WEIGHT_CONTRADICTION": ("CANNOT_VERIFY", None),
    "MISSING_STRENGTH": ("CANNOT_VERIFY", "RX-PRODUCT-004"),
    "AMBIGUOUS_HANDWRITING": ("CANNOT_VERIFY", None),
    "OUT_OF_SCOPE_AGE": ("OUT_OF_SCOPE", "RX-SCOPE-003"),
}


@dataclass
class BenchCase:
    case_id: str
    split: str
    product: str
    mutation: str
    expected_state: str
    expected_rule: str | None
    language: str
    handwritten: bool
    hand_font: str | None
    perturbation_rx: str
    perturbation_label: str
    rx: dict[str, Any]
    label: dict[str, Any]
    patient: dict[str, str]
    dispense_date: str = "2026-09-19"
    gold_rx: list[dict[str, Any]] = field(default_factory=list)
    gold_label: list[dict[str, Any]] = field(default_factory=list)


def _fmt_ml(v: float) -> str:
    s = f"{v:.2f}".rstrip("0").rstrip(".")
    return f"{s} mL"


def _regimen(p: dict[str, Any], weight: float, strength_mg: float, per_ml: float) -> tuple[str, int, float]:
    """A WHO-consistent dose volume, frequency and mg per dose for this weight and strength."""
    if "bands" in p:
        for lo, hi, mg, per_day in p["bands"]:
            if lo <= weight < hi:
                break
        mg_dose = mg
    else:
        mg_dose = p["mgkg_dose"] * weight
        per_day = p["per_day"]
    vol = mg_dose * per_ml / strength_mg
    vol = round(vol * 10) / 10  # measurable to 0.1 mL
    return _fmt_ml(vol), per_day, vol


def make_case(i: int, rng: random.Random, split: str, products: list[str], fonts: list[str], perturbations: list[str],
              mutation: str) -> BenchCase:
    eligible = [x for x in products if PRODUCTS[x]["indications"] or mutation != "DURATION_CHANGE"]
    product = rng.choice(eligible)
    p = PRODUCTS[product]
    language = "fr" if rng.random() < 0.25 else "en"
    handwritten = rng.random() < 0.45 or mutation == "AMBIGUOUS_HANDWRITING"
    hand_font = rng.choice(fonts) if handwritten else None
    weight = round(rng.uniform(7.0, 24.0) * 2) / 2
    age_months = int(max(6, min(130, (weight - 4) * 7 + rng.uniform(-6, 6))))
    age_text = f"{age_months} months" if age_months < 24 else f"{age_months // 12} years"
    if language == "fr":
        age_text = age_text.replace("months", "mois").replace("years", "ans")
    options = [s for s in p["strengths"] if _regimen(p, weight, s[1][0], s[2])[2] <= 15] or [max(p["strengths"], key=lambda s: s[1][0])]
    s_text, comps, per_ml = rng.choice(options)
    dose_text, per_day, vol = _regimen(p, weight, comps[0], per_ml)
    indication, days = rng.choice(p["indications"]) if p["indications"] else (None, 3)
    freq_text = rng.choice(FREQ_TEXT[language][per_day])
    total = vol * per_day * days
    bottle = next((v for v in (50, 60, 70, 75, 80, 100, 120, 150, 200, 250) if v >= total + 5), int(total // 50 + 1) * 50)
    clinic, clinic_line = rng.choice(CLINICS)
    lot = f"LOT {rng.choice('ABCDEFGHKLMNPRSTWX')}{rng.randint(1000, 99999)}"
    expiry = f"EXP {rng.randint(1, 12):02d}/{rng.choice([2027, 2028])}"
    rx = dict(clinic=clinic, clinic_line=clinic_line, prescriber=rng.choice(PRESCRIBERS), date="2026-09-18",
              patient=rng.choice(PATIENTS), age=age_text, weight=f"{weight:g} kg".replace(".", "," if language == "fr" and rng.random() < 0.5 else "."),
              allergies="None known" if language == "en" else "Aucune connue", drug=p["rx"], strength=s_text, dose=dose_text,
              frequency=freq_text, duration=DAYS_TEXT[language].format(d=days), indication=indication, language=language,
              handwritten=handwritten, hand_font=hand_font or "Caveat.ttf", seed=i)
    label = dict(generic=p["label"], form=p["form"], strength=s_text, volume=f"{bottle} mL (when reconstituted)", lot=lot,
                 expiry=expiry, manufacturer=rng.choice(MANUFACTURERS), gtin=f"0{rng.randint(10**12, 10**13 - 1)}", accent=p["accent"], seed=i)
    patient = {"patient.weight": f"{weight:g} kg", "patient.age": age_text.replace("mois", "months").replace("ans", "years"),
               "patient.allergies": "none", "patient.medications": "none"}

    # ---- mutation
    m = mutation
    if m == "STRENGTH_SWAP":
        others = [s for s in p["strengths"] if s[0] != s_text] or [("100 mg/5 mL", [100], 5)]
        label["strength"] = rng.choice(others)[0]
        if len(p["strengths"]) == 1:
            label["strength"] = s_text.replace("200 mg/40 mg", "400 mg/80 mg").replace("200 mg/5 mL", "100 mg/5 mL")
    elif m == "DECIMAL_SHIFT":
        rx["dose"] = _fmt_ml(vol * 10)
        label["volume"] = "250 mL (when reconstituted)"
    elif m == "DOSE_VOLUME_CHANGE":
        rx["dose"] = _fmt_ml(round(vol * (3.2 if product == "azithromycin" else 2.2), 1))
        label["volume"] = "250 mL (when reconstituted)"
    elif m == "FREQUENCY_CHANGE":
        wrong = {1: 3, 2: 4, 3: 1, 4: 1}[per_day] if product != "amoxicillin" else 4
        rx["frequency"] = FREQ_TEXT[language][wrong][0]
        label["volume"] = "250 mL (when reconstituted)"
    elif m == "DURATION_CHANGE":
        rx["duration"] = DAYS_TEXT[language].format(d=days + 5 if days < 10 else 14)
        label["volume"] = "250 mL (when reconstituted)"
    elif m == "DRUG_IDENTITY_SWAP":
        other = rng.choice([k for k in PRODUCTS if k != product and k != "azithromycin"])
        label["generic"], label["form"] = PRODUCTS[other]["label"], PRODUCTS[other]["form"]
        label["strength"] = PRODUCTS[other]["strengths"][0][0]
    elif m == "FORMULATION_CHANGE":
        label["form"] = "Tablets USP"
        label["strength"] = f"{comps[0] * 2:g} mg tablet" if len(comps) == 1 else f"{comps[0] * 2:g} mg/{comps[1] * 2:g} mg tablet"
        label["volume"] = "20 tablets"
    elif m == "ALLERGY_INSERTION":
        cls = {"amoxicillin": "penicillin", "amoxicillin+clavulanic_acid": "penicillin", "cefalexin": "cephalosporins",
               "sulfamethoxazole+trimethoprim": "sulfa drugs", "clarithromycin": "macrolides", "azithromycin": "macrolides"}[product]
        patient["patient.allergies"] = cls
    elif m == "DUPLICATE_INGREDIENT":
        patient["patient.medications"] = {"amoxicillin+clavulanic_acid": "amoxicillin", "sulfamethoxazole+trimethoprim": "Bactrim"}.get(product, product.split("+")[0])
    elif m == "INTERACTION_INSERTION":
        patient["patient.medications"] = {"clarithromycin": "carbamazepine", "cefalexin": "metformin",
                                          "sulfamethoxazole+trimethoprim": "methotrexate"}.get(product, "warfarin")
    elif m == "EXPIRED_PRODUCT":
        label["expiry"] = f"EXP {rng.randint(1, 7):02d}/2026"
    elif m == "INSUFFICIENT_QUANTITY":
        label["volume"] = f"{max(1, int(total * 0.5))} mL (when reconstituted)"
    elif m == "WEIGHT_CONTRADICTION":
        patient["patient.weight"] = f"{weight + 6:g} kg"
    elif m == "MISSING_STRENGTH":
        rx["strength"] = None
    elif m == "AMBIGUOUS_HANDWRITING":
        alt = _fmt_ml(round(vol + 5, 1)) if vol < 5 else _fmt_ml(round(max(vol - 5, 1), 1))
        rx["ambiguous_dose"] = (dose_text, alt)
    elif m == "OUT_OF_SCOPE_AGE":
        patient["patient.age"] = "14 years"
        rx["age"] = "14 years" if language == "en" else "14 ans"
    state, rule = MUTATIONS[m]
    pert = rng.choice(perturbations)
    pert_l = rng.choice(perturbations)
    return BenchCase(case_id=f"rb{i:04d}", split=split, product=product, mutation=m, expected_state=state, expected_rule=rule,
                     language=language, handwritten=handwritten, hand_font=hand_font, perturbation_rx=pert,
                     perturbation_label=pert_l, rx=rx, label=label, patient=patient)


SPLITS = {
    # train: fonts Caveat+Reenie, perturbations minus the held-out families, products minus clarithromycin
    "train": {"fonts": ["Caveat.ttf", "ReenieBeanie.ttf"], "perts": ["clean", "blur", "glare", "jpeg", "rotation", "low_res"],
              "products": ["amoxicillin", "amoxicillin+clavulanic_acid", "cefalexin", "sulfamethoxazole+trimethoprim", "azithromycin"]},
    "val": {"fonts": ["Caveat.ttf", "ReenieBeanie.ttf"], "perts": ["clean", "blur", "glare", "jpeg", "rotation", "low_res"],
            "products": ["amoxicillin", "amoxicillin+clavulanic_acid", "cefalexin", "sulfamethoxazole+trimethoprim", "azithromycin"]},
    # test: an unseen handwriting font, unseen perturbation families and an unseen product
    "test": {"fonts": ["NanumPenScript.ttf"], "perts": ["clean", "motion_blur", "shadow", "occlusion", "perspective"],
             "products": list(PRODUCTS)},
}


def generate(out: Path, n_train: int, n_val: int, n_test: int, seed: int = 7) -> list[BenchCase]:
    rng = random.Random(seed)
    cases: list[BenchCase] = []
    i = 0
    muts = list(MUTATIONS)
    for split, n in (("train", n_train), ("val", n_val), ("test", n_test)):
        cfg = SPLITS[split]
        for k in range(n):
            mutation = "NONE" if k % 3 == 0 else muts[1 + (k // 3 + k) % (len(muts) - 1)]
            c = make_case(i, rng, split, cfg["products"], cfg["fonts"], cfg["perts"], mutation)
            cases.append(c)
            i += 1
    out.mkdir(parents=True, exist_ok=True)
    for c in cases:
        render_case(c, out)
    (out / "cases.jsonl").write_text("\n".join(json.dumps(asdict(c), ensure_ascii=False) for c in cases), encoding="utf-8")
    return cases


def render_case(c: BenchCase, out: Path) -> None:
    rx_spec = RxSpec(**{k: v for k, v in c.rx.items() if k in RxSpec.__dataclass_fields__})
    lab_spec = LabelSpec(**{k: (tuple(v) if k == "accent" else v) for k, v in c.label.items() if k in LabelSpec.__dataclass_fields__})
    seed = int(c.case_id[2:])
    rx_scene = perturb(document_photo(render_prescription(rx_spec), seed=seed), c.perturbation_rx, seed=seed)
    lab_scene = perturb(bottle_photo(render_label(lab_spec), seed=seed + 1), c.perturbation_label, seed=seed + 1)
    for scene, name in ((rx_scene, "rx"), (lab_scene, "label")):
        img = scene.image
        if max(img.size) > 1600:
            ratio = 1600 / max(img.size)
            img = img.resize((int(img.width * ratio), int(img.height * ratio)))
        img.save(out / f"{c.case_id}_{name}.jpg", quality=90)
    c.gold_rx = rx_scene.gold()
    c.gold_label = lab_scene.gold()


def gold_fields(c: BenchCase) -> dict[str, Any]:
    """The facts a perfect reader would produce for this case, as snapshot input fields."""
    rx, lab = c.rx, c.label
    f: dict[str, Any] = {"rx.drug": rx["drug"], "rx.frequency": rx["frequency"], "rx.duration": rx["duration"],
                         "rx.patient_age": rx["age"], "rx.patient_weight": rx["weight"], "rx.allergies": rx["allergies"],
                         "dispensed.drug": f"{lab['generic']} {lab['form']}", "dispensed.strength": lab["strength"],
                         "dispensed.volume": lab["volume"], "dispensed.lot": lab["lot"], "dispensed.expiry": lab["expiry"]}
    if rx.get("ambiguous_dose"):
        f["rx.dose"] = None
    else:
        f["rx.dose"] = rx["dose"]
    if rx.get("strength"):
        f["rx.strength"] = rx["strength"]
    if rx.get("indication"):
        f["rx.indication"] = rx["indication"]
    f.update(c.patient)
    return {k: v for k, v in f.items() if v is not None}
