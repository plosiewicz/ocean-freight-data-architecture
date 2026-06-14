"""GCS Bronze landing — idempotent write-once upload primitive.

The Bronze tier is immutable: ``upload_if_absent`` no-ops when the target object
already exists, so an accidental re-run cannot overwrite a landed object (the
write-once idempotency contract, D-06/D-09; threat T-03-02). Auth is via
Application Default Credentials (ADC) — no committed key file (threat T-03-01).

The ``storage.Client`` is constructed lazily inside ``get_client()`` so importing
this module in a unit test (no network, no creds) does not fail; tests monkeypatch
``get_client``.

Provenance: 03-RESEARCH.md § Idempotent GCS landing / § Auth; idempotency pattern
maps to /Users/plosiewicz/Desktop/supply-chain/lib/import_runner.py (no-op re-run).
"""

from __future__ import annotations

from google.cloud import storage

GCP_PROJECT: str = "data-architecture-msds683"

_client: storage.Client | None = None


def get_client() -> storage.Client:
    """Return a process-wide GCS client (ADC creds), constructing it lazily.

    Lazy so that ``import lib.gcs`` succeeds offline in tests; the network/creds
    are only touched when a caller actually needs the client.
    """
    global _client
    if _client is None:
        _client = storage.Client(project=GCP_PROJECT)
    return _client


def upload_if_absent(bucket_name: str, key: str, local_path: str) -> bool:
    """Upload ``local_path`` to ``gs://{bucket_name}/{key}`` only if absent.

    Returns ``True`` when the object was uploaded, ``False`` when it already
    existed (write-once no-op). This is the Bronze immutability contract.
    """
    blob = get_client().bucket(bucket_name).blob(key)
    if blob.exists():
        print(f"[SKIP] gs://{bucket_name}/{key} (write-once, exists)")
        return False
    blob.upload_from_filename(local_path)
    print(f"[OK] landed gs://{bucket_name}/{key}")
    return True
