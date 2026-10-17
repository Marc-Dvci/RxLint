# Security model

## Untrusted input

Every image, recording and web page is untrusted data.

* **Photos and speech.** Nemotron 3 Nano Omni returns a fixed JSON schema of transcribed fields.
  The schema has no field for a verdict, and fields outside the schema are rejected. Text printed
  on a label that addresses a machine is flagged (`untrusted_instructions_seen`) and has no path to
  the verdict: the kernel only consumes typed facts parsed by RxLint's own grammar.
* **Web pages.** Tavily results are filtered against the country allowlist by hostname before use,
  and matching is deterministic string logic. Page text is never placed in a system prompt; when
  Nemotron 3 Ultra lists documents for drift detection, each title must occur verbatim in the
  retrieved text.
* **Explanations.** Model-written text may not contain a digit outside a placeholder token. The
  values behind the tokens come from the verified result.

## Case access

* A case identifier names a case; it does not grant access to it. Creating a case returns a random
  256-bit access token, and only its SHA-256 is stored. The browser keeps the token in an HttpOnly,
  `SameSite=Strict` cookie scoped to that case's own API path; API clients send it as the
  `X-RxLint-Case-Token` header. Every case endpoint (result, events, photos, confirmation,
  explanation, live check, report, deletion) checks it in constant time and answers 404 without it,
  so a guessed identifier reveals nothing.
* Cases are deleted after `RXLINT_CASE_RETENTION_HOURS` (default 24), and the creator can delete a
  case at once from the case page. Photos and reports are served with `Cache-Control: no-store`.
* This is access control for a demonstration, not a clinical deployment. Production use with patient
  information needs authenticated staff accounts, role-based authorisation, audit logging,
  encryption at rest, a retention policy set by the institution and the safeguards its health-data
  law requires.

## Data handling

* Patient names are not needed and not requested. The demo cases are fictional.
* Uploaded assets are hashed with SHA-256 on arrival and stored under `RXLINT_DATA`. Deleting a
  case removes its images, evidence and report.
* Model calls send only the image or recording being read, or the structured findings being
  explained. Live checks send product, lot and country, never patient facts.
* Uploads are capped at 12 MB per file. Static file serving is confined to the built web bundle.

## Reporting

Please report a vulnerability privately through the repository's security advisory page.
