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

## Data handling

* Patient names are not needed and not requested. Case identifiers are random.
* Uploaded assets are hashed with SHA-256 on arrival and stored under `RXLINT_DATA`. Deleting a
  case directory removes its images, evidence and report.
* Model calls send only the image or recording being read, or the structured findings being
  explained. Live checks send product, lot and country, never patient facts.
* Uploads are capped at 12 MB per file. Static file serving is confined to the built web bundle.

## Reporting

Please report a vulnerability privately through the repository's security advisory page.
