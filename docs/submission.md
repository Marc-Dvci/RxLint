# RxLint submission story and Devpost fields

---

## About the project

# RxLint: static analysis for medication dispensing

**RxLint checks the medicine being handed over against the prescription, the way a compiler checks code.** Start with two photos, or import a FHIR prescription and photograph the bottle, then add the patient's weight, age and allergies. Every finding traces to the source evidence, exact arithmetic and WHO or FDA rule behind it.

Independent **PP-OCRv6** checks and a validation-calibrated reliability head keep uncertain readings under review. **Batch confirmation** presents unresolved values together, while supported **FHIR prescriptions** enter directly with source evidence.

- **Who it is for:** whoever makes the last check before a medicine crosses the counter, in a city pharmacy, a hospital outpatient pharmacy or a clinic dispensary, and the caregiver who gives the dose at home.
- **Reads** on Nebius Token Factory: a vision model transcribes each photo and **NVIDIA Nemotron 3 Nano** turns the transcript into typed facts, each citing the line it was copied from.
- **Decides** in a deterministic kernel: **59 versioned rules** from the WHO AWaRe antibiotic book and FDA labels. A model never decides a verdict.
- **Explains** with **Nemotron 3 Ultra** in English, French and Arabic, and **Nemotron 3 Nano** audits every sentence against the verified result.
- **Watches the regulators** with **Tavily** in the United States, France, the United Kingdom, Kenya and Nigeria: an exact-match lot search on ansm.sante.fr finds the ANSM recall that names the lot on the bottle.
- **Measured** on 120 held-out cases: **95.0% exact verdicts after simulated confirmation**, **9/10 overwritten doses held for review**, and **0/80 false-safe verdicts**, both before and after confirmation.

**Try it:** [live app](https://rxlint-284853036406.europe-west1.run.app) · [demo and captions](https://github.com/Marc-Dvci/RxLint/releases/tag/submission-demo) · [code](https://github.com/Marc-Dvci/RxLint) (Apache-2.0)

![RxLint flags the wrong concentration on case A: the verdict, the boxed strengths on both photos, and the calculation](https://raw.githubusercontent.com/Marc-Dvci/RxLint/main/docs/img/case_A.png)

**The drug name is right. The volume is right. The bottle is still wrong.** A prescription for amoxicillin/clavulanate 400 mg/57 mg per 5 mL, 5 mL twice daily, is filled with a 250 mg/62.5 mg per 5 mL bottle. The product name and prescribed volume match, but the concentrations differ. A 9.5 kg child receives 52.6 mg/kg/day instead of the 80 to 90 mg/kg/day WHO gives, with 1.75 times more clavulanate per milligram of amoxicillin. RxLint catches this in one scan, draws a box around both strengths on the photos, and shows the arithmetic and the WHO rule that fired.

## Inspiration

WHO estimates the global cost of medication errors at **US$42 billion a year**, and medicines account for nearly half of preventable harm in medical care. Pediatric oral antibiotics concentrate the risk: doses are computed per kilogram, the same product ships in several liquid concentrations, and caregivers measure in millilitres at home. The final check before a bottle crosses the counter is a person comparing two pieces of paper.

Software engineering solved a similar problem decades ago. A compiler does not ask whether code *sounds* plausible: it parses the input into typed objects, applies deterministic rules, points at the exact line of a violation, and refuses to build when information is missing. I built RxLint to bring that discipline to the pharmacy counter. Frontier models are excellent at reading the messy physical world. The decision itself belongs to code that can be inspected, versioned and replayed.

## What it does

The person dispensing (a pharmacist, a pharmacy technician or a nurse) photographs the prescription and the medicine being handed over, or supplies a supported **FHIR R4 MedicationRequest** and a bottle photo, then adds weight, age, allergies and current medicines. RxLint returns one of four verdicts:

- **PASS**: every mandatory fact is present and every applicable rule passed.
- **REVIEW**: at least one deterministic rule failed.
- **CANNOT VERIFY**: a required fact is missing, unreadable or contradictory, and RxLint asks for the smallest clarification that unblocks it.
- **OUT OF SCOPE**: the medicine, route or patient is outside the installed rule pack.

![Case D: an overwritten dose requires an explicit choice; confirm reviewed values and the kernel re-runs to PASS without another model call](https://raw.githubusercontent.com/Marc-Dvci/RxLint/main/docs/img/confirm.gif)

Every finding opens into what was observed, the calculation, the rule with its verbatim source quote and page, and the required action. Clicking a fact highlights the pixels it was read from. Nemotron 3 Ultra explains the result to the person dispensing or to the caregiver in **English, French and Arabic**, and a reviewed phrase table covers **Swahili**. A separate **live regulator plane** asks whether the FDA, ANSM, EMA, MHRA, Kenya's PPB, NAFDAC or WHO has published anything about this product and this lot since the rule pack was frozen. Every case exports as an HTML report with a pharmacist sign-off block and a JSON evidence bundle with the hashes of the photos, the rule pack and the result.

The first rule pack covers **seven oral antibiotic products for children aged 28 days to 12 years**: **59 versioned rules** transcribed from the **WHO AWaRe antibiotic book (2022), Table 50.1** and the infection chapters, and from **seven FDA prescribing labels**. All **73 source quotes** are checked verbatim against the cited page by an automated test.

**Review unresolved facts together.** Fixed FHIR prescription facts keep their JSON-path evidence, and all unresolved fields appear in one confirmation card with explicit choices for ambiguous readings. Confirming the reviewed values re-runs the deterministic checks without another inference call.

![FHIR prescription import and batch confirmation in the working app](https://raw.githubusercontent.com/Marc-Dvci/RxLint/main/docs/img/fhir_batch.png)

### Where it fits

RxLint sits at the last step of dispensing: after the bottle is picked and labelled, before it crosses the counter. It needs a phone camera and a browser, and nothing changes in the pharmacy's own system. The verdict, every pharmacist confirmation and the photo hashes go into the report and the evidence bundle, which can be filed with the dispensing record. Rules are versioned YAML data with their sources, so a formulary update ships as a new hashed rule pack, reviewed like a release.

## How I built it

RxLint separates reading, proving and explaining, and gives each job to the component best suited to it.

![RxLint architecture: Nemotron reads and explains, a deterministic kernel decides, Tavily watches the regulators](https://raw.githubusercontent.com/Marc-Dvci/RxLint/main/docs/img/architecture.png)

**Reading, with NVIDIA Nemotron on Nebius Token Factory.** Token Factory serves the Nemotron models as text models, so the hosted reader splits the job: a Token Factory vision model (DeepSeek V4.1 Flash) only transcribes each photo line by line, with uncertain characters written as `[2|7]`. **Nemotron 3 Nano** turns the transcript into fields, and every value must be a verbatim copy of the transcript line it cites, or it is rejected. RxLint also detects which photo is the prescription and which is the bottle from the transcript itself, so a swapped upload is read correctly. **Nemotron 3 Nano Omni** supports a single-call photo reader at a configured Nebius AI Cloud or local llama.cpp endpoint. The published benchmark evaluates the hosted transcription-plus-Nano pipeline.

**Corroborating, with PP-OCRv6 and a trained head.** High-risk photo readings need matching independent OCR, an explicit supplied value or pharmacist confirmation (P-PERC-02); a focused re-read can recover small print only when independent OCR supports it. A **calibrated LightGBM reliability head** adds a second gate using OCR agreement, grammar, formulary plausibility, local sharpness and box agreement (P-PERC-03), with its threshold selected on validation before testing. Ambiguous readings remain explicit choices, and all fields needing review can be confirmed together.

**Proving, with a deterministic kernel.** Readings pass through a strict unit grammar in exact decimal arithmetic (decimal commas, `q8h`, `BID`, `2 fois par jour`; household measures and alternatives fail closed) into an evidence graph where every fact points back to its source pixels or statement. The kernel evaluates rules stored as YAML data: product identity, concentration, weight-based dose with WHO weight bands, interval, maximum daily dose, duration by indication, allergy contraindications, a published set of 13 interactions, duplicates, expiry and supplied quantity. The same snapshot and rule pack always produce the same result hash.

**Explaining, with Nemotron 3 Ultra and an audit by Nemotron 3 Nano.** When a case is blocked, **Nemotron 3 Ultra** picks the smallest clarification from a closed list. On request it explains the verdict to a pharmacist or a caregiver, writing only the connecting sentences around placeholder tokens that carry every value with its unit, every medicine name and the action. An integrity check rejects any digit outside a token, and **Nemotron 3 Nano audits the rendered text** with closed questions generated from the findings ("does the text say the dose is too low or too high?"). A text that contradicts the verified result falls back to a deterministic phrase table. Before a language may show model-written text, a canary run plants errors in it: Nemotron 3 Nano caught every planted error in English, French and Arabic, so those languages show Nemotron 3 Ultra's text, and Swahili readers get the reviewed phrase table.

**Live intelligence, with Tavily.** The dispensing country selects an allowlist of regulator domains before any search runs. Code builds the queries from the canonical product, lot and country. The lot query quotes the lot code with Tavily's `exact_match`, so only pages that print this lot come back; every URL is re-checked by hostname; Tavily Extract (advanced depth, Markdown) reads a deterministic shortlist; and a lot matcher classifies each notice as a recall of this lot, a recall of this product, other lots only, a safety communication or supply information. For the United States, the openFDA enforcement feed runs alongside. For the other supported countries, RxLint searches regulator publications through Tavily: for a French prescription dispensed on 4 February 2019, Tavily finds the **ANSM recall of 18 January 2019** that names lot JA0287 on the bottle, and the same product with lot JA0290 stays clear. In the US demo, a check dated 20 November 2025 finds **FDA recall D-0151-2026** for the exact lot. The same allowlist monitors the rule sources themselves: newer WHO guidance on a monitored topic opens a review item for the rules that topic covers, and the installed rule never changes at runtime.

![Case I: Tavily's exact-match lot search on ansm.sante.fr returns the ANSM recall of 18 January 2019 naming lot JA0287, next to the PASS from the rules](https://raw.githubusercontent.com/Marc-Dvci/RxLint/main/docs/img/case_I_live.png)

The backend is **Python and FastAPI** with live progress over server-sent events; the frontend is **React and TypeScript** in a Google Material design; the service runs as a **Docker** container on **Google Cloud Run**, and the hosted model calls go to **Nebius Token Factory**.

## Measuring it: RxLintBench

I built a benchmark alongside the product. A renderer produces prescription and bottle photos with pixel-exact ground truth, a mutation engine injects one known error per case across **16 error families**, and photo perturbations (blur, glare, occlusion, perspective, low resolution) degrade them. The test fold holds out an unseen handwriting font, four unseen perturbation families and one unseen product. The mutation oracle agrees with the kernel on **1,700 of 1,700** generated cases.

On the held-out test fold (120 cases: 40 clean, 60 with a rule violation, 20 with a missing or overwritten fact), with DeepSeek V4.1 Flash and Nemotron 3 Nano reading every photo on Token Factory:

![Exact field reading on 120 held-out cases: dose 82.5%, weight 85.0%, label strength 93.3%, expiry 84.2%](https://raw.githubusercontent.com/Marc-Dvci/RxLint/main/docs/img/benchmark_fields.png)

| System | Overwritten dose held | Exact verdict after confirmation | False-safe after confirmation |
|---|---|---|---|
| Readings trusted as read | 3/10 | 85.8% | 4/80 |
| **RxLint** | **9/10** | **95.0%** | **0/80** |
| OCR + regex + the same kernel | 6/10 | 92.5% | 1/80 |

RxLint holds **9/10 overwritten doses** for confirmation and accepts **zero incorrect high-risk readings** across 677 evaluated readings. **54/120 cases (45.0%)** need confirmation. Exact field reading is **82.5% for dose**, **85.0% for weight**, **93.3% for label strength** and **84.2% for expiry**. The reliability head has test AUC **0.9805**; its threshold was selected on validation and frozen before test extraction.

All three systems use the same cases and deterministic kernel. An error case returned as PASS is counted as false-safe; RxLint records **0/80** before and after confirmation. Its final exact verdict count is **114/120**, including **38/40** clean cases returned as PASS. Confirmation is simulated from written ground truth, so these rendered cases measure prototype performance rather than clinical safety. [Evaluation, audit and reproduction](https://github.com/Marc-Dvci/RxLint/blob/main/docs/implementation_audit.md).

A separate pilot uses **12 openly licensed medicine photographs**, with attribution and source hashes: **8/10 identities**, **4/9 strengths** and **5/6 volumes** are read exactly, with **zero incorrect evaluated fields accepted**. Liquid concentration is **4/5** and solid strength **0/4**, making solid packaging a priority for broader coverage. This single-annotator perception pilot includes one failed control read; paired prescriptions and independent pharmacist assessment are the next validation stage. [Photo dataset and complete results](https://github.com/Marc-Dvci/RxLint/blob/main/benchmarks/real_world/README.md).

## Challenges I ran into

- **Reading small print without guessing.** PP-OCRv6, bounded crop recovery and explicit ambiguity checks corroborate dose, weight, concentration and expiry readings; a validation-calibrated second gate accepted zero incorrect high-risk readings in the test fold. Batch confirmation keeps the remaining review work in one place.
- **Faithful explanations in several languages.** Values carry their units in locked tokens, and Nemotron 3 Nano audits the surrounding claims against the verified result. Planted-error checks enable model text in English, French and Arabic; Swahili uses reviewed phrases.
- **Reliable regulator context and edge cases.** Domain checks, exact lot matching and notice-context filtering prevent unrelated links from becoming recall alerts. The deterministic kernel, FHIR import and confirmation flow are covered by **251 automated tests**, with all **ten demo cases** returning their expected verdict.

## Accomplishments that I'm proud of

- A complete product that checks photographed or supported FHIR prescriptions against the actual bottle, with source evidence and batch confirmation.
- **Measured prototype performance:** **95.0% exact verdicts after simulated confirmation**, **93.3% exact label-strength reading**, and **zero incorrect high-risk readings accepted** on 120 held-out cases.
- **Every warning is inspectable**: the source pixels, the exact decimal arithmetic, the rule version, the verbatim WHO or FDA quote with its page, and the model calls that produced each reading.
- **Language is kept at the boundary.** The same case explained in English, French, Arabic or Swahili keeps the same rule IDs, the same calculations and the same result hash.
- **A live regulator check that knows the difference between a lot and a product**, demonstrated on a real FDA recall and a real ANSM recall, each with a negative control.

## What I learned

- The most reliable use of a frontier model is **reading**, and the most reliable home for a safety decision is **code**. Nemotron handles transcription structure and explanation; the kernel keeps every verdict inspectable.
- **Independent evidence beats self-reported confidence.** Independent OCR agreement and a calibrated reliability head expose uncertainty that a reader alone can miss.
- **Explanations need verification too.** Locking the numbers is the start; auditing the claims a sentence makes is what keeps a translation faithful.
- **Freshness is its own engineering problem.** A frozen, hashed rule pack and a live, allowlisted regulator check answer two different questions, and keeping them apart makes both trustworthy.

## What's next for RxLint

- **Pharmacy pilots with 30-50 de-identified paired cases and independent annotation**, with the pharmacist's sign-off captured in the report, plus MedicationDispense integration alongside the supported MedicationRequest import.
- **More rule packs**: adult antibiotics, renal dose adjustment, and institution-specific formularies, each versioned and signed.
- **Nemotron 3 Nano Omni on a Nebius AI Cloud endpoint** as the single-call reader, with the transcription path as a second independent reader.
- **Continuous surveillance** of the rule sources on a schedule, feeding a reviewed pack release process.

---

## Built with

(25 tags)

nvidia-nemotron, nemotron-3-ultra, nemotron-3-nano, nemotron-3-nano-omni, nebius-token-factory, nebius, tavily, python, fastapi, pydantic, lightgbm, scikit-learn, rapidocr, opencv, react, typescript, vite, docker, google-cloud-run, llama.cpp, deepseek, openfda, who-aware, fhir-r4, pytest

---

## "Try it out" links

- Live app: https://rxlint-284853036406.europe-west1.run.app
- Code: https://github.com/Marc-Dvci/RxLint

## Image gallery


1. `case_A.png`: Case A. Right drug, right volume, wrong bottle: RxLint returns REVIEW and boxes both strengths.
2. `architecture.png`: Nemotron reads and explains, a deterministic kernel decides, Tavily watches the regulators.
3. `fhir_batch.png`: FHIR prescription evidence and all unresolved values confirmed together.
4. `case_I_live.png`: Tavily finds the ANSM recall that names the lot on the bottle.
5. `benchmark_fields.png`: Exact dose, weight, concentration and expiry reading on 120 held-out cases.

## Video demo link

https://github.com/Marc-Dvci/RxLint/releases/download/submission-demo/rxlint-demo.mp4

## Which track are you submitting your project into?

Best apps and agents

---

## Which model(s) did you use, and why did you choose that size/variant?

- **Nemotron 3 Nano 30B-A3B** (`nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B`, Token Factory) for the everyday calls: turning each photo transcript into fields with cited line numbers, and auditing every explanation with closed questions. Structuring runs in about three seconds and the track guidance points the fast, frequent calls at Nano, so every case uses it.
- **Nemotron 3 Ultra 550B-A55B** (`nvidia/Nemotron-3-Ultra-550b-a55b`, Token Factory) for the calls where reasoning and multilingual writing matter: choosing the smallest clarification when a case is blocked, and writing pharmacist and caregiver explanations in English, French and Arabic. It runs only when a case is blocked or an explanation is requested, and it answered with schema-valid JSON in under a second.
- **Nemotron 3 Nano Omni 30B-A3B** (IQ4_XS GGUF through llama.cpp on an RTX 4070) for the optional single-call photo and voice-note reader. The hosted benchmark reports the transcription-plus-Nano path.
- **Nemotron 3.5 Lightning** (`nvidia/Nemotron-3_5-Lightning`, Token Factory), Super and Ultra were evaluated as structuring or explanation-audit alternatives. Nano is the deployed model for these frequent calls.
- For the hosted product, the NVIDIA models on Token Factory are text models, so a Token Factory vision model (DeepSeek V4.1 Flash) transcribes the photo and Nemotron does everything that interprets, reasons or checks.

## How would you rate Nemotron's output quality for your use case? (1 = Poor, 10 = Excellent)

**8.** Nemotron 3 Nano reliably structures English and French transcripts into cited fields under strict JSON schemas, and Nemotron 3 Ultra produces fluent explanations and focused clarifications. The implementation addresses model uncertainty with independent OCR and a calibrated gate, and checks explanation claims against the deterministic result; English, French and Arabic passed the planted-error checks, while Swahili uses reviewed phrases.

## Did you fine-tune, prompt-engineer, or use Nemotron out of the box? What was your approach?

Out of the box, with prompt engineering, strict structured output and deterministic validation around every call. Each role has a narrow contract: transcription only, structuring with verbatim line citations, a clarification from a closed enum, or prose around placeholder tokens. Every response is validated against a Pydantic schema, and a value that fails validation is discarded. On top of the generative readers I trained a calibrated **LightGBM reliability head** on the benchmark's ground truth, which estimates per reading the probability that it is exactly right. All model responses are recorded and replayable, so every result is reproducible.

## How did Nemotron's performance compare to other models you've used for similar tasks?

Nemotron 3 Nano is suited to frequent schema-constrained structuring and audit calls, while Ultra handles clarification and multilingual explanation. RxLintBench measures the complete system rather than claiming a controlled ranking against unrelated models: trusting the hosted reader's output gives **85.8%** exact verdicts and **4/80** false-safe verdicts after simulated confirmation; applying independent corroboration and the calibrated gate gives **95.0%** and **0/80** respectively. The head and threshold were selected before test extraction.

## Which Nebius platform capabilities were most valuable to your project and how?

**Nebius Token Factory** is the runtime for every model call in the hosted product.

- **What I used it for.** Three roles, each with its own model id and settings: `vision` (DeepSeek V4.1 Flash) transcribes each photo, `structure` (Nemotron 3 Nano) turns the transcript into cited fields and audits every explanation, `ultra` (Nemotron 3 Ultra) picks clarifications and writes explanations. The service is a stateless Docker container with scale-to-zero, so hosted GPU inference runs on Token Factory's serverless capacity. Focused crop reads are bounded to three per image and run only when needed; every inference records its latency and token counts.
- **What worked well.** The OpenAI-compatible API let one client route every role, and point the same role at a local llama.cpp server during development by changing one base URL. `response_format: json_schema` gave schema-valid output from Nemotron 3 Nano and Ultra, which made strict Pydantic validation practical. `GET /v1/models?verbose=true` returns each model's modality, prices, rate limits, regions and supported features: I used it to pick models and to confirm which ones accept images. Sending an image to a text model returns a clear `This model does not support image input`.
- **Onboarding, zero to hello world.** The first Nemotron response was a standard chat-completions request with a base URL and a key. The one thing that needed reading was the thinking default (below).
- **Integration improvement.** Explicit thinking controls, including top-level `reasoning_effort=none`, keep narrow extraction calls focused on their structured response, and replay keys distinguish model, endpoint and settings.
- **What would improve the platform.** EU placement or region pinning for every role, plus serverless NVIDIA vision and audio models. The public demo uses fictional cases; voice notes are already supported where Nano Omni is served.
- **Would I build with it again?** Yes: hosted inference avoids maintaining a GPU service, role-based routing sends frequent calls to Nano and occasional reasoning to Ultra, and the same client supports Token Factory and a local server.

## How likely are you to recommend running Nemotron on Nebius to other developers? (1 = Unlikely, 10 = Highly Likely)

**8.** The API is standard, the latency is excellent (Ultra under a second, Nano about three seconds for structuring), JSON schema output works, and the catalog covers the whole Nemotron 3 family from Nano to Ultra. A serverless Nemotron vision or omni model would raise it further, because perception is where a product like this starts.

## How would you rate your experience running Nemotron inference on Nebius compared to previous cloud or local development environments? (1 = Poor, 10 = Excellent)

**8.** Compared with running Nemotron 3 Nano Omni locally (about 14 s per image and 21 GB of RAM on a 12 GB GPU), Token Factory removed all infrastructure work and made Ultra-class reasoning available in under a second. Compared with other managed clouds I have used, setup was quicker: one key, a standard SDK, and structured output that behaves as documented.

## What additional features or improvements would have made the Nemotron on Nebius experience more effective for your project?

- **Nemotron 3 Nano Omni (or a Nemotron VL model) on Token Factory serverless**, so a single NVIDIA model can read the photo, the spoken note and the transcript.
- **Token log-probabilities for vision outputs**, so an application can gate a transcribed digit on the model's own uncertainty.
- **Per-key spend caps and rate limits** configurable in the console, for public demos.
- **EU-region placement** for Nemotron 3 Ultra and for a vision model, or a region pin per request, for health data.
- **Clear examples of thinking controls per model**: model-specific template controls and top-level `reasoning_effort=none` keep narrow extraction calls focused on structured output.
- **Replay-friendly request IDs and a documented model-version string** in each response, for audit trails.

## What do you most hope to see from the Nemotron team next?

A serverless omni model with calibrated, per-field confidence, and stronger multilingual performance in lower-resource languages such as Swahili, where a safety explanation has to be as reliable as in English.

## Did you use Tavily in your project?

**Yes.** Every live regulator check makes runtime calls to Tavily Search (restricted to the dispensing country's regulator domains) and Tavily Extract (on a deterministic shortlist), and the rule-source drift monitor uses Tavily Extract on the WHO publication page and Tavily Search on who.int.
