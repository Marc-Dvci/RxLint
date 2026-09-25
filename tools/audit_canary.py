"""Does the explanation audit catch a planted error in each language?

For every supported language, a correct caregiver text and texts with one planted error (strengths said
to match; dose said to be above the range when the kernel found it below) are audited, both as the token
template and as rendered text with numbers. A language may show model-written explanations only when the
audit passes every correct text and rejects every planted error in it (see AUDITED_LANGUAGES in
rxlint.reasoning.explain).

    RXLINT_MODEL_MODE=record python tools/audit_canary.py
"""
import json
from pathlib import Path

from rxlint.config import load_env

load_env()
from rxlint.models.client import ModelClient
from rxlint.reasoning.explain import audit, render

TOKENS = {"rx_strength": "400 mg / 57 mg per 5 mL", "dispensed_strength": "250 mg / 62.5 mg per 5 mL", "weight": "9.5 kg",
          "dose": "52.63 mg/kg/day", "range": "80–90 mg/kg/day", "action": "{{action}}"}
ITEMS = [{"claim": "strength_mismatch"}, {"claim": "dose_below_range"}]

# (correct, strengths said to match, dose said to be above the range)
TEXTS = {
    "en": ("The prescription says {{rx_strength}}, but the bottle is {{dispensed_strength}}. For a child of {{weight}}, this gives {{dose}}, below the recommended {{range}}. {{action}}",
           "The bottle strength {{dispensed_strength}} is the same as the prescription. For a child of {{weight}}, this gives {{dose}}, below the recommended {{range}}. {{action}}",
           "The prescription says {{rx_strength}}, but the bottle is {{dispensed_strength}}. For a child of {{weight}}, this gives {{dose}}, above the recommended {{range}}. {{action}}"),
    "fr": ("L'ordonnance indique {{rx_strength}}, mais le flacon est dosé à {{dispensed_strength}}. Pour un enfant de {{weight}}, cela donne {{dose}}, en dessous de la plage recommandée de {{range}}. {{action}}",
           "Le dosage du flacon {{dispensed_strength}} est identique à celui de l'ordonnance. Pour un enfant de {{weight}}, cela donne {{dose}}, en dessous de la plage recommandée de {{range}}. {{action}}",
           "L'ordonnance indique {{rx_strength}}, mais le flacon est dosé à {{dispensed_strength}}. Pour un enfant de {{weight}}, cela donne {{dose}}, au-dessus de la plage recommandée de {{range}}. {{action}}"),
    "ar": ("الوصفة تذكر {{rx_strength}}، لكن الزجاجة تركيزها {{dispensed_strength}}. لطفل وزنه {{weight}}، هذا يعطي {{dose}}، أقل من النطاق الموصى به {{range}}. {{action}}",
           "تركيز الزجاجة {{dispensed_strength}} مطابق لما في الوصفة. لطفل وزنه {{weight}}، هذا يعطي {{dose}}، أقل من النطاق الموصى به {{range}}. {{action}}",
           "الوصفة تذكر {{rx_strength}}، لكن الزجاجة تركيزها {{dispensed_strength}}. لطفل وزنه {{weight}}، هذا يعطي {{dose}}، أعلى من النطاق الموصى به {{range}}. {{action}}"),
    "sw": ("Cheti kinasema {{rx_strength}}, lakini chupa ina {{dispensed_strength}}. Kwa mtoto wa {{weight}}, hii inatoa {{dose}}, chini ya kiwango kinachopendekezwa cha {{range}}. {{action}}",
           "Nguvu ya chupa {{dispensed_strength}} ni sawa na ya cheti. Kwa mtoto wa {{weight}}, hii inatoa {{dose}}, chini ya kiwango kinachopendekezwa cha {{range}}. {{action}}",
           "Cheti kinasema {{rx_strength}}, lakini chupa ina {{dispensed_strength}}. Kwa mtoto wa {{weight}}, hii inatoa {{dose}}, juu ya kiwango kinachopendekezwa cha {{range}}. {{action}}"),
}
ACTION = {"en": "Do not give this medicine until a pharmacist has checked it.",
          "fr": "Ne donnez pas ce médicament avant qu'un pharmacien l'ait vérifié.",
          "ar": "لا تعطِ هذا الدواء حتى يتحقق منه الصيدلي.",
          "sw": "Usimpe mtoto dawa hii hadi mfamasia aikague."}


def main() -> None:
    client = ModelClient()
    out: dict[str, dict[str, bool]] = {}
    for lang, (ok, match, above) in TEXTS.items():
        row = {}
        for form in ("tokens", "rendered"):
            tok = {**TOKENS, "action": ACTION[lang]}
            conv = (lambda t: t.replace("{{action}}", ACTION[lang])) if form == "tokens" else (lambda t: render(t, tok))
            row[f"{form}: correct passes"] = not audit(client, conv(ok), ITEMS, "REVIEW", "caregiver")["problems"]
            row[f"{form}: 'match' caught"] = bool(audit(client, conv(match), ITEMS, "REVIEW", "caregiver")["problems"])
            row[f"{form}: 'above' caught"] = bool(audit(client, conv(above), ITEMS, "REVIEW", "caregiver")["problems"])
        out[lang] = row
        print(lang, json.dumps(row))
    model = client.config("structure").model
    dest = Path(__file__).resolve().parents[1] / "benchmarks" / "results" / "audit_canary.json"
    dest.write_text(json.dumps({"auditor": model, "results": out}, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
