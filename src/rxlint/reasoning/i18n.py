"""Deterministic phrase table for the four tested languages.

Anything a caregiver must not misread comes from this table: the verdict, the action (with its
negation) and the unit words. Models write only the sentences around these phrases.
"""

from __future__ import annotations

LANGUAGES = {
    "en": {"name": "English", "dir": "ltr"},
    "fr": {"name": "Français", "dir": "ltr"},
    "ar": {"name": "العربية", "dir": "rtl"},
    "sw": {"name": "Kiswahili", "dir": "ltr"},
}

STATE = {
    "PASS": {"en": "No discrepancy found", "fr": "Aucune anomalie détectée", "ar": "لم يُعثر على أي تعارض", "sw": "Hakuna tofauti iliyopatikana"},
    "REVIEW": {"en": "Needs pharmacist review", "fr": "Vérification par le pharmacien nécessaire", "ar": "يحتاج إلى مراجعة الصيدلي", "sw": "Inahitaji ukaguzi wa mfamasia"},
    "CANNOT_VERIFY": {"en": "Cannot be verified yet", "fr": "Vérification impossible pour l'instant", "ar": "لا يمكن التحقق بعد", "sw": "Haiwezi kuthibitishwa bado"},
    "OUT_OF_SCOPE": {"en": "Outside this checker's scope", "fr": "Hors du périmètre de ce contrôle", "ar": "خارج نطاق هذا الفحص", "sw": "Nje ya wigo wa ukaguzi huu"},
}

ACTION = {
    "REVIEW": {
        "en": "Do not give this medicine until a pharmacist has checked it.",
        "fr": "Ne donnez pas ce médicament tant qu'un pharmacien ne l'a pas vérifié.",
        "ar": "لا تُعطِ هذا الدواء قبل أن يتحقق منه الصيدلي.",
        "sw": "Usimpe mtoto dawa hii hadi mfamasia aikague.",
    },
    "CANNOT_VERIFY": {
        "en": "Do not give this medicine yet. The pharmacist needs to complete the check first.",
        "fr": "Ne donnez pas encore ce médicament. Le pharmacien doit d'abord terminer la vérification.",
        "ar": "لا تُعطِ هذا الدواء بعد. يجب على الصيدلي إكمال الفحص أولاً.",
        "sw": "Usimpe mtoto dawa hii bado. Mfamasia anahitaji kukamilisha ukaguzi kwanza.",
    },
    "OUT_OF_SCOPE": {
        "en": "The pharmacist will check this medicine directly.",
        "fr": "Le pharmacien vérifiera ce médicament directement.",
        "ar": "سيتحقق الصيدلي من هذا الدواء مباشرة.",
        "sw": "Mfamasia ataikagua dawa hii moja kwa moja.",
    },
    "PASS": {
        "en": "Give the medicine exactly as the pharmacist explained.",
        "fr": "Donnez le médicament exactement comme le pharmacien l'a expliqué.",
        "ar": "أعطِ الدواء تماماً كما شرح الصيدلي.",
        "sw": "Mpe mtoto dawa kama mfamasia alivyoeleza.",
    },
}

# Plain-language reason for each rule family, used when no model explanation is available.
REASON = {
    "concentration_match": {
        "en": "The strength written on the prescription ({rx}) is different from the strength printed on this bottle ({bottle}). The same number of millilitres would give a different amount of medicine.",
        "fr": "Le dosage écrit sur l'ordonnance ({rx}) est différent de celui imprimé sur ce flacon ({bottle}). Le même nombre de millilitres donnerait une quantité différente de médicament.",
        "ar": "التركيز المكتوب في الوصفة ({rx}) مختلف عن التركيز المطبوع على هذه القارورة ({bottle}). نفس عدد المليلترات سيعطي كمية مختلفة من الدواء.",
        "sw": "Nguvu ya dawa iliyoandikwa kwenye cheti ({rx}) ni tofauti na iliyochapishwa kwenye chupa hii ({bottle}). Mililita zile zile zingetoa kiasi tofauti cha dawa.",
    },
    "identity_match": {
        "en": "The medicine in the bottle ({bottle}) is not the medicine on the prescription ({rx}).",
        "fr": "Le médicament du flacon ({bottle}) n'est pas celui de l'ordonnance ({rx}).",
        "ar": "الدواء الموجود في القارورة ({bottle}) ليس هو الدواء المذكور في الوصفة ({rx}).",
        "sw": "Dawa iliyo kwenye chupa ({bottle}) si dawa iliyo kwenye cheti ({rx}).",
    },
    "weight_dose": {
        "en": "For a child weighing {weight} kg, this dose works out to {value} {unit}, outside the guideline range of {range}.",
        "fr": "Pour un enfant de {weight} kg, cette dose correspond à {value} {unit}, en dehors de l'intervalle recommandé de {range}.",
        "ar": "لطفل وزنه {weight} كغ، تعادل هذه الجرعة {value} {unit}، وهي خارج النطاق الموصى به {range}.",
        "sw": "Kwa mtoto mwenye uzito wa kilo {weight}, dozi hii ni {value} {unit}, nje ya kiwango kinachopendekezwa cha {range}.",
    },
    "allergy_contraindication": {
        "en": "An allergy was reported ({allergy}) that matters for this type of medicine ({product}).",
        "fr": "Une allergie a été signalée ({allergy}) qui concerne ce type de médicament ({product}).",
        "ar": "تم الإبلاغ عن حساسية ({allergy}) تخص هذا النوع من الأدوية ({product}).",
        "sw": "Mzio umeripotiwa ({allergy}) unaohusu aina hii ya dawa ({product}).",
    },
    "expiry": {
        "en": "The date printed on the bottle ({expiry}) needs checking against the treatment dates.",
        "fr": "La date imprimée sur le flacon ({expiry}) doit être vérifiée par rapport aux dates du traitement.",
        "ar": "يجب التحقق من التاريخ المطبوع على القارورة ({expiry}) مقارنةً بتواريخ العلاج.",
        "sw": "Tarehe iliyochapishwa kwenye chupa ({expiry}) inahitaji kukaguliwa dhidi ya tarehe za matibabu.",
    },
    "quantity": {
        "en": "The bottle holds {supplied_ml} mL but the full course needs {needed_ml} mL.",
        "fr": "Le flacon contient {supplied_ml} mL mais le traitement complet nécessite {needed_ml} mL.",
        "ar": "تحتوي القارورة على {supplied_ml} مل لكن العلاج الكامل يحتاج إلى {needed_ml} مل.",
        "sw": "Chupa ina mL {supplied_ml} lakini matibabu yote yanahitaji mL {needed_ml}.",
    },
    "_default": {
        "en": "A check on this medicine needs a pharmacist's attention.",
        "fr": "Un contrôle de ce médicament nécessite l'attention du pharmacien.",
        "ar": "يحتاج أحد فحوصات هذا الدواء إلى اهتمام الصيدلي.",
        "sw": "Ukaguzi mmoja wa dawa hii unahitaji uangalizi wa mfamasia.",
    },
    "_cannot": {
        "en": "Part of the prescription or the label could not be read with certainty.",
        "fr": "Une partie de l'ordonnance ou de l'étiquette n'a pas pu être lue avec certitude.",
        "ar": "لم يكن بالإمكان قراءة جزء من الوصفة أو الملصق بشكل مؤكد.",
        "sw": "Sehemu ya cheti au lebo haikuweza kusomwa kwa uhakika.",
    },
    "_pass": {
        "en": "The prescription and the bottle match, and the dose is within the guideline range for the child's weight. This covers the checks listed in the report.",
        "fr": "L'ordonnance et le flacon correspondent, et la dose est dans l'intervalle recommandé pour le poids de l'enfant. Cela couvre les contrôles listés dans le rapport.",
        "ar": "الوصفة والقارورة متطابقتان، والجرعة ضمن النطاق الموصى به لوزن الطفل. يشمل ذلك الفحوصات المذكورة في التقرير.",
        "sw": "Cheti na chupa vinalingana, na dozi iko ndani ya kiwango kinachopendekezwa kwa uzito wa mtoto. Hii inahusu ukaguzi ulioorodheshwa kwenye ripoti.",
    },
    "_oos": {
        "en": "This medicine or this patient is outside the checks this tool performs.",
        "fr": "Ce médicament ou ce patient est hors du périmètre des contrôles de cet outil.",
        "ar": "هذا الدواء أو هذا المريض خارج نطاق الفحوصات التي تجريها هذه الأداة.",
        "sw": "Dawa hii au mgonjwa huyu yuko nje ya ukaguzi unaofanywa na zana hii.",
    },
}

UNITS = {
    "mg/kg/day": {"en": "mg/kg/day", "fr": "mg/kg/jour", "ar": "ملغ/كغ/يوم", "sw": "mg/kg/siku"},
    "mg/kg/dose": {"en": "mg/kg/dose", "fr": "mg/kg/prise", "ar": "ملغ/كغ/جرعة", "sw": "mg/kg/dozi"},
}
