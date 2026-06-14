"""Tests for scripts/load_bronze.py — the idempotent synthetic Bronze loader.

The loader is the files->Bronze step of the Brambles generator/loader split:
generators stay pure (local JSONL), this maps each generated JSONL to its
deterministic ``synthetic/`` Bronze key (D-04 prefix, D-05 dt= partition) and
lands it via ``lib.gcs.upload_if_absent`` (write-once, no-op-if-exists, D-06/D-09).

No network: ``lib.gcs.upload_if_absent`` is mocked; stub JSONL files live under
``tmp_path``.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

import pytest

from scripts import load_bronze


@pytest.fixture
def in_dir(tmp_path: Path) -> Path:
    """A dir with the three generated stub JSONL files."""
    for name in ("bookings.jsonl", "container_events.jsonl", "schedules.jsonl"):
        (tmp_path / name).write_text(
            json.dumps({"provenance": "synthetic"}) + "\n", encoding="utf-8"
        )
    return tmp_path


def test_load_bronze_keys(in_dir: Path) -> None:
    """Each local JSONL maps to its deterministic synthetic/ Bronze key (D-04/D-05)."""
    mapping = load_bronze.bronze_key_map(in_dir, dt="2024-01-01")
    assert mapping[in_dir / "bookings.jsonl"] == "synthetic/bookings/dt=2024-01-01/bookings.jsonl"
    assert mapping[in_dir / "container_events.jsonl"] == "synthetic/events/dt=2024-01-01/container_events.jsonl"
    assert mapping[in_dir / "schedules.jsonl"] == "synthetic/schedules/dt=2024-01-01/schedules.jsonl"


def test_load_bronze_calls_upload_once(in_dir: Path) -> None:
    """upload_if_absent is called exactly once per discovered JSONL, with the key."""
    with mock.patch.object(load_bronze.lib.gcs, "upload_if_absent", return_value=True) as up:
        rc = load_bronze.main(["--in-dir", str(in_dir), "--dt", "2024-01-01", "--bucket", "test-bucket"])
    assert rc == 0
    assert up.call_count == 3
    called_keys = {call.args[1] for call in up.call_args_list}
    assert called_keys == {
        "synthetic/bookings/dt=2024-01-01/bookings.jsonl",
        "synthetic/events/dt=2024-01-01/container_events.jsonl",
        "synthetic/schedules/dt=2024-01-01/schedules.jsonl",
    }
    for call in up.call_args_list:
        assert call.args[0] == "test-bucket"  # bucket
        assert Path(call.args[2]).exists()    # local_path


def test_load_bronze_idempotent(in_dir: Path) -> None:
    """When upload_if_absent returns False (exists), no new objects land (D-06/D-09)."""
    with mock.patch.object(load_bronze.lib.gcs, "upload_if_absent", return_value=False) as up:
        rc = load_bronze.main(["--in-dir", str(in_dir), "--dt", "2024-01-01", "--bucket", "test-bucket"])
    assert rc == 0
    # called for each file, but all reported as no-op skips (write-once).
    assert up.call_count == 3


def test_load_bronze_missing_file_fails_loud(tmp_path: Path) -> None:
    """A missing expected JSONL fails loud (run `make generate` first)."""
    (tmp_path / "bookings.jsonl").write_text("{}\n", encoding="utf-8")  # only one of three
    with mock.patch.object(load_bronze.lib.gcs, "upload_if_absent", return_value=True):
        rc = load_bronze.main(["--in-dir", str(tmp_path), "--dt", "2024-01-01", "--bucket", "test-bucket"])
    assert rc != 0
