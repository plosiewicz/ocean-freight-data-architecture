"""Shared pytest fixtures for the lib helper unit tests.

No network: the GCS fixtures use unittest.mock so upload_if_absent can be
exercised offline (no ADC creds required).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

import lib.seeds


@pytest.fixture
def seed() -> int:
    """The central determinism seed."""
    return lib.seeds.SEED


@pytest.fixture
def tmp_jsonl_dir(tmp_path: Path) -> Path:
    """A throwaway directory for JSONL write tests."""
    return tmp_path


@pytest.fixture
def fake_blob() -> MagicMock:
    """A mock GCS blob. Default: object is absent (.exists() -> False)."""
    blob = MagicMock(name="blob")
    blob.exists.return_value = False
    return blob


@pytest.fixture
def fake_client(fake_blob: MagicMock) -> MagicMock:
    """A mock storage.Client whose .bucket(...).blob(...) returns fake_blob."""
    client = MagicMock(name="client")
    client.bucket.return_value.blob.return_value = fake_blob
    return client
