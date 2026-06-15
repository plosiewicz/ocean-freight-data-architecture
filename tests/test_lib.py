"""Unit tests for the shared lib helpers (jsonl, seeds, gcs).

Behaviors (03-PLAN.md Task 2):
- write_jsonl is byte-stable: ensure_ascii=False, LF, trailing LF, one object
  per line, insertion order preserved (no sort_keys).
- per-entity seed offsets are distinct integers.
- upload_if_absent no-ops when the blob exists; uploads exactly once when absent.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import lib.gcs
import lib.seeds
from lib.jsonl import write_jsonl


def test_write_jsonl_byte_stable(tmp_jsonl_dir: Path) -> None:
    # Rows include a non-ASCII char (port name) and intentionally non-sorted keys
    # to prove ensure_ascii=False + insertion-order preservation (no sort_keys).
    rows = [
        {"_key": "p1", "name": "Göteborg", "calls": 3},
        {"_key": "p2", "name": "Málaga", "calls": 1},
    ]
    a = tmp_jsonl_dir / "a.jsonl"
    b = tmp_jsonl_dir / "b.jsonl"

    n1 = write_jsonl(a, rows)
    n2 = write_jsonl(b, rows)

    assert n1 == n2 == 2
    raw_a = a.read_bytes()
    # Byte-identical across two writes of the same input.
    assert raw_a == b.read_bytes()
    # LF line endings, trailing LF, no CR.
    assert b"\r" not in raw_a
    assert raw_a.endswith(b"\n")
    assert raw_a.count(b"\n") == 2  # one trailing LF per row, no extras
    # ensure_ascii=False: non-ASCII chars stored as UTF-8, not \uXXXX escapes.
    assert "Göteborg".encode("utf-8") in raw_a
    assert b"\\u" not in raw_a
    # Insertion order preserved: "_key" must appear before "name" before "calls".
    first_line = raw_a.split(b"\n")[0].decode("utf-8")
    assert first_line.index('"_key"') < first_line.index('"name"') < first_line.index('"calls"')


def test_seeds_offsets_distinct() -> None:
    # The new Phase-4 OPERATED_BY_OFFSET is included so its distinctness from the
    # three Phase-3 offsets (1000/2000/3000) is ACTIVELY guarded — not trivially
    # passing (04-03-PLAN.md amended acceptance criterion).
    offsets = (
        lib.seeds.BOOKINGS_OFFSET,
        lib.seeds.EVENTS_OFFSET,
        lib.seeds.SCHEDULES_OFFSET,
        lib.seeds.OPERATED_BY_OFFSET,
    )
    derived = {lib.seeds.SEED + off for off in offsets}
    # Four distinct derived stream seeds => independent reproducible streams.
    assert len(derived) == len(offsets) == 4
    # The raw offsets themselves must also be distinct integers.
    assert len(set(offsets)) == 4
    for off in offsets:
        assert isinstance(off, int)


def test_upload_if_absent_noop(monkeypatch, fake_client: MagicMock, fake_blob: MagicMock) -> None:
    monkeypatch.setattr(lib.gcs, "get_client", lambda: fake_client)

    # Case 1: object already exists -> no-op, no upload, returns False.
    fake_blob.exists.return_value = True
    result = lib.gcs.upload_if_absent("bkt", "bronze/x.parquet", "/tmp/x.parquet")
    assert result is False
    fake_blob.upload_from_filename.assert_not_called()

    # Case 2: object absent -> uploads exactly once, returns True.
    fake_blob.exists.return_value = False
    result = lib.gcs.upload_if_absent("bkt", "bronze/y.parquet", "/tmp/y.parquet")
    assert result is True
    fake_blob.upload_from_filename.assert_called_once_with("/tmp/y.parquet")
