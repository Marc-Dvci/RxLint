"""The RxLint demo narration, one section per voice clip, one cue per sentence.

Each sentence is a beat: ``say`` is what the voice reads, ``cap`` is the caption drawn on screen
while it is spoken (``None`` keeps the previous caption). ``narrate.py`` synthesises every section
and measures where each sentence starts; ``tour.js`` cues its visuals to those measurements.
"""

SECTIONS = [
    {
        "id": "home",
        "sentences": [
            {"say": "RxLint is a medication-checking assistant for pharmacists and clinic nurses dispensing antibiotics to children.",
             "cap": "RxLint: medication checks for pharmacists and clinic nurses caring for children."},
            {"say": "It checks the bottle against the prescription and patient details, flagging potential errors with evidence before the medicine is handed over.",
             "cap": "Check the bottle, prescription and patient details. See potential errors and the evidence."},
            {"say": "Here, a child is prescribed amoxicillin clavulanate at 400 milligrams per 5 millilitres.",
             "cap": "Prescribed: amoxicillin/clavulanate 400 mg per 5 mL, 5 mL twice daily."},
            {"say": "The bottle contains 250: the same medicine, but a weaker concentration than prescribed.",
             "cap": "Dispensed: 250 mg per 5 mL. The same volume delivers less than prescribed."},
        ],
    },
    {
        "id": "read",
        "sentences": [
            {"say": "Two photos, or a FHIR prescription and a bottle photo.",
             "cap": "Photograph the prescription, or import a FHIR R4 order; verify the actual bottle."},
            {"say": "On Nebius Token Factory, a vision model transcribes each photo, and NVIDIA Nemotron 3 Nano turns the transcript into typed facts, each citing the line it was copied from.",
             "cap": "Nemotron 3 Nano structures the transcript. Every value cites the line it was copied from."},
            {"say": "PP-OCRv6 checks high-risk numbers, with a calibrated second gate.",
             "cap": "PP-OCRv6 corroboration + a validation-calibrated reliability head."},
            {"say": "Then a deterministic kernel applies 59 rules from the WHO AWaRe book.",
             "cap": "59 rules from the WHO AWaRe antibiotic book. Deterministic arithmetic, no model call."},
            {"say": "Click any fact, and RxLint shows the pixels it was read from.",
             "cap": "Click a fact: RxLint points at the pixels it was read from."},
        ],
    },
    {
        "id": "finding",
        "sentences": [
            {"say": "The verdict is REVIEW.",
             "cap": "REVIEW: at least one deterministic rule failed."},
            {"say": "The critical finding shows what was read: 400 per 5 prescribed, 250 per 5 dispensed.",
             "cap": "Observed: 400 mg / 57 mg per 5 mL prescribed, 250 mg / 62.5 mg per 5 mL dispensed."},
            {"say": "The calculation is right there: 80 milligrams per millilitre against 50.",
             "cap": "Calculation: 400 / 5 = 80 mg/mL prescribed, 250 / 5 = 50 mg/mL dispensed."},
            {"say": "The rule source is quoted verbatim: every finding links the pixels, the arithmetic, and the rule.",
             "cap": "Every finding links the pixels, the arithmetic and the rule it rests on."},
        ],
    },
    {
        "id": "explain",
        "sentences": [
            {"say": "Nemotron 3 Ultra explains the result to the caregiver, in English, French or Arabic.",
             "cap": "Nemotron 3 Ultra explains the verified result in English, French and Arabic."},
            {"say": "It writes around locked values, so it can never invent a number.",
             "cap": "Values are locked tokens: the model writes the sentences, never a number."},
            {"say": "And Nemotron 3 Nano audits every sentence against the verified result before it is shown.",
             "cap": "Nemotron 3 Nano audits each explanation against the verified result."},
        ],
    },
    {
        "id": "handwriting",
        "sentences": [
            {"say": "When the handwriting is overwritten, 2.5 or 7.5 millilitres, RxLint does not guess.",
             "cap": "Case D: the dose is overwritten. 2.5 or 7.5 mL?"},
            {"say": "It returns CANNOT VERIFY, and Nemotron 3 Ultra picks the single smallest question to ask.",
             "cap": "CANNOT VERIFY. Nemotron 3 Ultra picks the smallest clarification from a closed list."},
            {"say": "Reviewed values are confirmed together, with explicit choices for ambiguity.",
             "cap": "Batch confirmation: review all unresolved values together; choose ambiguous readings explicitly."},
            {"say": "The rules re-run without another model call, and the case passes.",
             "cap": "The kernel re-runs on the confirmed value. No new model call."},
        ],
    },
    {
        "id": "live",
        "sentences": [
            {"say": "The rule pack is frozen and hashed, so a separate live plane asks: has a regulator published anything since?",
             "cap": "Plane B: has a regulator published anything since the rule pack was frozen?"},
            {"say": "For this French dispensing check, Tavily searches ANSM for pages naming the exact lot.",
             "cap": "Tavily Search on ansm.sante.fr only, exact match on the lot code, then Tavily Extract."},
            {"say": "For this bottle, dispensed in February 2019, ANSM had recalled lot JA0287.",
             "cap": "LIVE REVIEW: the ANSM recall of 18 January 2019 names lot JA0287."},
            {"say": "The live state sits next to the verdict; it never changes it.",
             "cap": "The live state never edits the deterministic verdict."},
        ],
    },
    {
        "id": "bench",
        "sentences": [
            {"say": "On 120 held-out cases, RxLint accepted zero incorrect high-risk readings.",
             "cap": "0 incorrect high-risk readings accepted across 677 evaluated readings."},
            {"say": "Forty-five percent of cases need confirmation, and label-strength accuracy is 93.3 percent.",
             "cap": "Confirmation requested on 54/120 cases. Label-strength accuracy: 93.3%."},
            {"say": "95 percent exact verdicts after simulated confirmation, against 85.8 when readings are trusted, with nine of ten overwritten doses held.",
             "cap": "95.0% exact verdicts after simulated confirmation vs 85.8%; 9/10 overwritten doses held. Synthetic test fold."},
        ],
    },
    {
        "id": "close",
        "sentences": [
            {"say": "A model may transcribe, report a competing reading, and write around locked values.",
             "cap": "A model may transcribe, report competing readings, choose a clarification, write around locked values."},
            {"say": "It may not compute a dose, decide the verdict, or write a number.",
             "cap": "It may not convert a unit, compute a dose, decide PASS or REVIEW, or write a number."},
            {"say": "RxLint: Nemotron on Nebius Token Factory reads and explains, a deterministic kernel decides, and Tavily watches the regulators.",
             "cap": "RxLint. Nemotron reads and explains. The kernel decides. Tavily watches the regulators."},
        ],
    },
]
