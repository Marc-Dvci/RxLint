# Clinical disclaimer

RxLint is a research prototype built for the Nebius x NVIDIA Global AI Hackathon. It is not a
medical device and is not approved for clinical use in any jurisdiction.

* A `PASS` means that no discrepancy was detected within the scope of the installed rule pack.
  It is not a statement that a treatment is safe, appropriate or effective.
* RxLint does not diagnose infections, choose antibiotics, or change a prescribed dose. Its only
  action on a discrepancy is to request professional review.
* The rule pack encodes a narrow, published subset of the WHO AWaRe antibiotic book (2022) and
  of U.S. prescribing information. The interaction check covers the 13 pairs listed in
  `rulepacks/pediatric-oral-antibiotics/rules/interactions.yaml` and nothing else.
* Live regulator intelligence retrieves notices from an allowlist of authoritative domains.
  A `LIVE_CLEAR` result means no applicable alert was retrieved during that check. It is not
  proof that no recall or warning exists.
* Rule values were transcribed from the cited sources, and an automated test checks each quote
  verbatim against the source text. A clinical deployment requires every rule to be reviewed by
  an independent clinical pharmacist under pack change control.
* Every image in the demo library and benchmark is synthetic. Names, clinics and manufacturers
  are fictional. Demo case G carries the lot number of FDA recall D-0151-2026 on a synthetic label.

The WHO AWaRe antibiotic book is distributed under CC BY-NC-SA 3.0 IGO. Excerpts are included in
`rulepacks/pediatric-oral-antibiotics/sources/` for verification, with attribution. A commercial
deployment would need a licensing review.
