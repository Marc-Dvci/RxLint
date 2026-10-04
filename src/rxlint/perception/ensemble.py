"""Two model readers may agree; independent OCR and the reliability gate still apply."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from ..core import Normalizer, load_pack
from ..models.client import ModelClient
from .extraction import Extraction, RawObservation, extract_image
from .reliability import canonical
from .transcribe import extract_two_stage


def merge(first: Extraction, second: Extraction) -> Extraction:
    """Keep agreements and every unresolved disagreement; confidence cannot erase ambiguity."""
    n = Normalizer(load_pack())
    observations = []
    agreement = {}
    for field in dict.fromkeys(o.field for ex in (first, second) for o in ex.observations):
        a = [o for o in first.observations if o.field == field]
        b = [o for o in second.observations if o.field == field]
        if not a or not b:
            observations.extend(a or b)
            agreement[field] = "single_reader"
            continue
        readings = a + b
        keys = {canonical(field, o.text, n) for o in readings}
        if len(keys) == 1 and None not in keys and all(o.legible and not o.alternatives for o in readings):
            observations.append(a[0].model_copy())
            agreement[field] = "dual_agreement"
        else:
            # Display a preferred reading, but carry all alternatives into the snapshot.
            preferred = a[0].model_copy()
            preferred.alternatives = list(dict.fromkeys([*preferred.alternatives,
                *[o.text for o in readings if o.text != preferred.text],
                *[alt for o in readings for alt in o.alternatives]]))
            preferred.legible = all(o.legible for o in readings)
            observations.append(preferred)
            agreement[field] = "disagreement"
    return Extraction(asset_id=first.asset_id, kind=first.kind, document_type=first.document_type,
        observations=observations, model=f"{first.model} + {second.model}",
        provider=f"{first.provider} + {second.provider}", replayed=first.replayed and second.replayed,
        latency_ms=max(first.latency_ms or 0, second.latency_ms or 0),
        untrusted_instructions_seen=first.untrusted_instructions_seen or second.untrusted_instructions_seen,
        legibility="partial" if any(not o.legible or o.alternatives for o in observations) else "good",
        rejected=first.rejected + second.rejected, reader_agreement=agreement,
        error="; ".join(e for e in (first.error, second.error) if e) or None)


def extract_ensemble(client: ModelClient, image: bytes, kind: str, asset_id: str, mime: str = "image/jpeg") -> Extraction:
    import os
    if not os.environ.get("RXLINT_OMNI_BASE_URL") or not client.available("omni"):
        return Extraction(asset_id=asset_id, kind=kind, error="ensemble needs a configured Nano Omni endpoint")
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(extract_two_stage, client, image, kind, asset_id, mime)
        second = pool.submit(extract_image, client, image, kind, asset_id, mime)
        return merge(first.result(), second.result())
