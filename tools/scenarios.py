"""Print the kernel verdict for the demo scenarios typed as structured facts."""
from rxlint.core import build_snapshot, load_pack, verify

BASE = {
    "rx.drug": "Amoxicillin/clavulanate oral suspension", "rx.strength": "400 mg/57 mg per 5 mL", "rx.dose": "5 mL",
    "rx.frequency": "twice daily", "rx.duration": "5 days", "rx.indication": "acute otitis media",
    "dispensed.drug": "Amoxicillin and Clavulanate Potassium for Oral Suspension", "dispensed.strength": "250 mg/62.5 mg per 5 mL",
    "dispensed.volume": "100 mL", "dispensed.expiry": "EXP 03/2027", "dispensed.lot": "LOT K4471",
    "patient.weight": "12 kg", "patient.age": "2 years", "patient.allergies": "none", "patient.medications": "none",
}
OK = {"dispensed.strength": "400 mg/57 mg per 5 mL"}
SCENARIOS = [
    ("A concentration mismatch", {}),
    ("F clean pass", OK),
    ("B arithmetic (10 mL)", {**OK, "rx.dose": "10 mL"}),
    ("B2 decimal shift (50 mL)", {**OK, "rx.dose": "50 mL"}),
    ("C allergy", {**OK, "patient.allergies": "penicillin (hives)"}),
    ("D ambiguous volume", {**OK, "rx.dose": "2.5 or 7.5 mL"}),
    ("no weight", {**OK, "patient.weight": []}),
    ("unknown drug", {"rx.drug": "Cefuroxime axetil suspension", "dispensed.drug": "Cefuroxime axetil", "dispensed.strength": "250 mg/5 mL", "rx.strength": "250 mg/5 mL"}),
    ("misread product", {**OK, "dispensed.drug": "Amoxicilin clavulanat"}),
    ("wrong drug", {**OK, "dispensed.drug": "Cefalexin for oral suspension", "dispensed.strength": "250 mg/5 mL"}),
    ("expired", {**OK, "dispensed.expiry": "EXP 08/2026"}),
    ("short supply 10d", {**OK, "rx.duration": "10 days", "rx.indication": "pharyngitis"}),
    ("interaction", {**OK, "patient.medications": "warfarin, paracetamol"}),
    ("neonate", {**OK, "patient.age": "10 days", "patient.weight": "3.4 kg"}),
    ("unknown allergy", {**OK, "patient.allergies": "grandma's syrup"}),
]


def run() -> None:
    pack = load_pack()
    for name, over in SCENARIOS:
        f = {**BASE, **over}
        f = {k: v for k, v in f.items() if v != []}
        v = verify(build_snapshot(f, pack, dispense_date="2026-09-19"), pack)
        print(f"\n=== {name}: {v.state} {v.summary}")
        for x in v.findings:
            if x.status in ("fail", "cannot_evaluate", "out_of_scope") or (x.type == "weight_dose"):
                print(f"  {x.status:15} {x.severity or '':13} {x.rule_id:22} {x.message}")
        if v.clarification:
            print("  clarify:", v.clarification["action"], v.clarification["fields"])


if __name__ == "__main__":
    run()
