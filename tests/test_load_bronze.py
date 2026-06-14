"""Tests for scripts/load_bronze.py — the idempotent synthetic Bronze loader.

The loader is the files->Bronze step of the Brambles generator/loader split:
generators stay pure (FLAT local JSONL); this splits each stream by **each
record's own natural date** (CR-03) and lands the per-day shards via
``lib.gcs.upload_if_absent`` (write-once, no-op-if-exists, D-04/D-05/D-06/D-09).

No network: ``lib.gcs.upload_if_absent`` is mocked; stub JSONL files live under
``tmp_path``.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

import pytest

from data_gen.network import EVENT_PARTITION_DT
from scripts import load_bronze


def _write_flat(in_dir: Path) -> None:
    """Write FLAT stub JSONL files whose dated records span multiple days.

    bookings span 2024-01-01..03; events span 2024-01-01, 2024-02-15, 2024-03-31;
    schedules are timeless (no per-record date field).
    """
    bookings = [
        {"booking_id": "bkg_0", "origin_unlocode": "USHOU", "dest_unlocode": "CNSHA", "booking_date": "2024-01-01", "provenance": "synthetic"},
        {"booking_id": "bkg_1", "origin_unlocode": "USLAX", "dest_unlocode": "JPTYO", "booking_date": "2024-02-10", "provenance": "synthetic"},
        {"booking_id": "bkg_2", "origin_unlocode": "USNYC", "dest_unlocode": "DEHAM", "booking_date": "2024-03-31", "provenance": "synthetic"},
    ]
    events = [
        {"event_id": "evt_0", "origin_unlocode": "USHOU", "dest_unlocode": "CNSHA", "event_ts": "2024-01-01T08:30:00", "provenance": "synthetic"},
        {"event_id": "evt_1", "origin_unlocode": "USLAX", "dest_unlocode": "JPTYO", "event_ts": "2024-02-15T14:05:00", "provenance": "synthetic"},
        {"event_id": "evt_2", "origin_unlocode": "USNYC", "dest_unlocode": "DEHAM", "event_ts": "2024-03-31T23:59:00", "provenance": "synthetic"},
    ]
    schedules = [
        {"service_id": "svc_0", "origin_unlocode": "USHOU", "dest_unlocode": "CNSHA", "provenance": "synthetic"},
        {"service_id": "svc_1", "origin_unlocode": "USLAX", "dest_unlocode": "JPTYO", "provenance": "synthetic"},
    ]
    (in_dir / "bookings.jsonl").write_text("\n".join(json.dumps(r) for r in bookings) + "\n", encoding="utf-8")
    (in_dir / "container_events.jsonl").write_text("\n".join(json.dumps(r) for r in events) + "\n", encoding="utf-8")
    (in_dir / "schedules.jsonl").write_text("\n".join(json.dumps(r) for r in schedules) + "\n", encoding="utf-8")


@pytest.fixture
def in_dir(tmp_path: Path) -> Path:
    """A dir with the three FLAT generated stub JSONL files."""
    _write_flat(tmp_path)
    return tmp_path


def test_build_shards_partitions_by_record_date(in_dir: Path, tmp_path: Path) -> None:
    """Each record lands under the dt= partition matching its OWN natural date (CR-03)."""
    shard_dir = tmp_path / "shards"
    shard_dir.mkdir()
    mapping = load_bronze.build_shards(in_dir, shard_dir)
    keys = set(mapping.values())

    # bookings: one shard per distinct booking_date
    assert "synthetic/bookings/dt=2024-01-01/bookings.jsonl" in keys
    assert "synthetic/bookings/dt=2024-02-10/bookings.jsonl" in keys
    assert "synthetic/bookings/dt=2024-03-31/bookings.jsonl" in keys

    # events: one shard per distinct event_ts calendar date (NOT all under 01-01)
    assert "synthetic/events/dt=2024-01-01/container_events.jsonl" in keys
    assert "synthetic/events/dt=2024-02-15/container_events.jsonl" in keys
    assert "synthetic/events/dt=2024-03-31/container_events.jsonl" in keys

    # schedules: timeless -> single anchor partition
    assert f"synthetic/schedules/dt={EVENT_PARTITION_DT}/schedules.jsonl" in keys

    # No event record sits under a wrong dt=: verify each shard's records match its dt.
    for shard_path, key in mapping.items():
        assert shard_path.exists()  # the per-day shard file was written
        dt_part = key.split("dt=")[1].split("/")[0]
        for raw in shard_path.read_text(encoding="utf-8").splitlines():
            if not raw.strip():
                continue
            rec = json.loads(raw)
            if "event_ts" in rec:
                assert rec["event_ts"][:10] == dt_part
            elif "booking_date" in rec:
                assert rec["booking_date"][:10] == dt_part


def test_partition_records_groups_by_date() -> None:
    """partition_records groups raw JSONL lines by each record's natural date."""
    lines = [
        json.dumps({"event_ts": "2024-01-01T01:00:00"}),
        json.dumps({"event_ts": "2024-03-31T23:00:00"}),
        json.dumps({"event_ts": "2024-01-01T05:00:00"}),
    ]
    by_dt = load_bronze.partition_records(lines, "event_ts", source="events")
    assert set(by_dt) == {"2024-01-01", "2024-03-31"}
    assert len(by_dt["2024-01-01"]) == 2
    assert len(by_dt["2024-03-31"]) == 1


def test_partition_records_missing_date_fails_loud() -> None:
    """A dated record missing its date field fails loud (never default-routed)."""
    lines = [json.dumps({"event_id": "evt_0"})]  # no event_ts
    with pytest.raises(ValueError):
        load_bronze.partition_records(lines, "event_ts", source="events")


def test_load_bronze_lands_each_shard_once(in_dir: Path) -> None:
    """upload_if_absent is called once per dt= shard, keyed to the record's date."""
    with mock.patch.object(load_bronze.lib.gcs, "upload_if_absent", return_value=True) as up:
        rc = load_bronze.main(["--in-dir", str(in_dir), "--bucket", "test-bucket"])
    assert rc == 0
    called_keys = {call.args[1] for call in up.call_args_list}
    # 3 booking days + 3 event days + 1 schedule anchor = 7 shard objects.
    assert up.call_count == 7
    assert "synthetic/events/dt=2024-02-15/container_events.jsonl" in called_keys
    assert "synthetic/bookings/dt=2024-02-10/bookings.jsonl" in called_keys
    assert f"synthetic/schedules/dt={EVENT_PARTITION_DT}/schedules.jsonl" in called_keys
    for call in up.call_args_list:
        assert call.args[0] == "test-bucket"  # bucket
        # local_path is a per-day shard under the loader's temp dir; it exists at
        # upload time (the temp dir is torn down only after main() returns).
        assert "dt=" in call.args[2]


def test_load_bronze_idempotent(in_dir: Path) -> None:
    """When upload_if_absent returns False (exists), no new objects land (D-06/D-09)."""
    with mock.patch.object(load_bronze.lib.gcs, "upload_if_absent", return_value=False) as up:
        rc = load_bronze.main(["--in-dir", str(in_dir), "--bucket", "test-bucket"])
    assert rc == 0
    assert up.call_count == 7  # called per shard, all reported as write-once no-ops


def test_load_bronze_missing_file_fails_loud(tmp_path: Path) -> None:
    """A missing expected JSONL fails loud (run `make generate` first)."""
    (tmp_path / "bookings.jsonl").write_text(
        json.dumps({"booking_date": "2024-01-01"}) + "\n", encoding="utf-8"
    )  # only one of three
    with mock.patch.object(load_bronze.lib.gcs, "upload_if_absent", return_value=True):
        rc = load_bronze.main(["--in-dir", str(tmp_path), "--bucket", "test-bucket"])
    assert rc != 0
