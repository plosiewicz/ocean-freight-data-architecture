"""RED-then-GREEN tests for the deterministic synthetic generators (ING-03, D-12).

Determinism contract under test (byte-identical from a fresh clone):
  - bookings.generate(seed) twice -> byte-identical JSONL; every row has
    provenance="synthetic" + conformed keys (origin/dest UN/LOCODE, carrier SCAC);
    booking_id is a deterministic counter (bkg_000000), never a uuid.
  - container_events.generate(...) twice -> byte-identical; delays drawn from the
    LPI-conditioned distribution; floats rounded; orphan-endpoint guard fails loud.
  - schedules.generate(...) twice -> byte-identical; service_frequency set from
    lane_weight; provenance + conformed keys.
  - NO wall-clock (no datetime.now) and NO uuid anywhere in data_gen/.

Small counts keep the run <30s (the real volume only runs in `make generate`).
"""

from __future__ import annotations

import json
import pathlib

import pytest

from data_gen import bookings, conditioning, container_events, network, schedules

DATA_GEN_DIR = pathlib.Path(__file__).resolve().parent.parent / "data_gen"


@pytest.fixture
def cond() -> conditioning.Conditioner:
    """A tiny in-memory Conditioner so generators run network-free + fast."""
    return conditioning.Conditioner(
        lsci_by_country={"USA": 90.0, "CHN": 80.0, "DEU": 70.0},
        comtrade_od={
            ("USA", "CHN"): 1_000_000.0,
            ("CHN", "USA"): 1_000_000.0,
            ("USA", "DEU"): 200_000.0,
            ("DEU", "USA"): 200_000.0,
        },
        lpi_by_country={"USA": 3.8, "CHN": 3.6, "DEU": 4.3},
        port_country={"USLAX": "USA", "CNSHA": "CHN", "DEHAM": "DEU"},
    )


def _jsonl_bytes(rows: list[dict]) -> bytes:
    return ("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n").encode("utf-8")


def test_bookings_deterministic(cond: conditioning.Conditioner) -> None:
    a = bookings.generate(seed=42, cond=cond, count=200)
    b = bookings.generate(seed=42, cond=cond, count=200)
    assert _jsonl_bytes(a) == _jsonl_bytes(b), "bookings must be byte-identical on re-run"
    assert len(a) == 200
    for i, row in enumerate(a):
        assert row["booking_id"] == f"bkg_{i:06d}", "booking_id is a deterministic counter"
        assert row["provenance"] == "synthetic"
        assert row["origin_unlocode"] in cond.port_country
        assert row["dest_unlocode"] in cond.port_country
        assert row["origin_unlocode"] != row["dest_unlocode"]
        assert isinstance(row["carrier_scac"], str) and len(row["carrier_scac"]) == 4


def test_events_deterministic(cond: conditioning.Conditioner) -> None:
    bk = bookings.generate(seed=42, cond=cond, count=50)
    a = container_events.generate(seed=7, cond=cond, bookings_rows=bk, count=300)
    b = container_events.generate(seed=7, cond=cond, bookings_rows=bk, count=300)
    assert _jsonl_bytes(a) == _jsonl_bytes(b), "events must be byte-identical on re-run"
    assert len(a) == 300
    booking_ids = {r["booking_id"] for r in bk}
    for row in a:
        assert row["provenance"] == "synthetic"
        assert row["booking_id"] in booking_ids, "every event references a real booking"
        # delay rounded to fixed decimals (Pitfall 7)
        assert round(row["delay_hours"], 2) == row["delay_hours"]
        assert row["delay_hours"] >= 0.0


def test_events_orphan_guard_fails_loud(cond: conditioning.Conditioner) -> None:
    """An event referencing a booking_id not in the input set must fail loud."""
    bogus = [{"booking_id": "bkg_999999", "origin_unlocode": "USLAX", "dest_unlocode": "CNSHA"}]
    # generate against an EMPTY booking set so any emitted ref is an orphan.
    with pytest.raises(RuntimeError):
        container_events.generate(seed=7, cond=cond, bookings_rows=bogus, count=10, _force_orphan=True)


def test_schedules_deterministic(cond: conditioning.Conditioner) -> None:
    a = schedules.generate(seed=99, cond=cond)
    b = schedules.generate(seed=99, cond=cond)
    assert _jsonl_bytes(a) == _jsonl_bytes(b), "schedules must be byte-identical on re-run"
    assert len(a) >= 1
    # Conformed-key set: the conditioner's mapped ports PLUS the US ports, since
    # US->US proforma rows (D-02) are emitted via a non-conditioner path and so
    # carry US UN/LOCODEs that need not appear in the fixture's port_country.
    conformed = set(cond.port_country) | set(network.US_PORTS)
    for row in a:
        assert row["provenance"] == "synthetic"
        assert row["origin_unlocode"] in conformed
        assert row["dest_unlocode"] in conformed
        assert isinstance(row["service_frequency"], int) and row["service_frequency"] >= 1


def test_schedules_us_us_lane_present(cond: conditioning.Conditioner) -> None:
    """A US->US proforma row is emitted via the non-conditioner path (D-02).

    The international LSCI x Comtrade conditioner zero-weights US->US pairs
    (RESEARCH A4 / Pitfall 1), so US->US proforma rows must appear regardless of
    the conditioner — even with a fixture whose port_country has only one US port.
    """
    rows = schedules.generate(seed=99, cond=cond)
    us_us = [
        r
        for r in rows
        if r["origin_unlocode"] in network.US_PORTS
        and r["dest_unlocode"] in network.US_PORTS
        and r["origin_unlocode"] != r["dest_unlocode"]
    ]
    assert us_us, "at least one US->US proforma row must be emitted (D-02)"
    # One row per directed US->US pair (origin != dest).
    expected_pairs = {
        (o, d) for o in network.US_PORTS for d in network.US_PORTS if o != d
    }
    got_pairs = {(r["origin_unlocode"], r["dest_unlocode"]) for r in us_us}
    assert got_pairs == expected_pairs, "every directed US->US pair must be present"
    for r in us_us:
        assert r["provenance"] == "synthetic"
        assert r["carrier_scac"] in network.CARRIER_SCACS
        assert isinstance(r["service_frequency"], int)
        assert r["service_frequency"] >= schedules.MIN_SERVICE_FREQUENCY


def test_schedules_byte_identical_with_us_us(cond: conditioning.Conditioner) -> None:
    """schedules.generate is byte-identical across two calls WITH US->US rows present."""
    a = schedules.generate(seed=99, cond=cond)
    b = schedules.generate(seed=99, cond=cond)
    assert _jsonl_bytes(a) == _jsonl_bytes(b), "schedules must be byte-identical on re-run"
    # The US->US rows are part of the deterministic output.
    assert any(
        r["origin_unlocode"] in network.US_PORTS and r["dest_unlocode"] in network.US_PORTS
        for r in a
    )


def test_no_wallclock_no_uuid() -> None:
    """No datetime.now / time.time / uuid anywhere in data_gen/ (D-12)."""
    offenders: list[str] = []
    for py in DATA_GEN_DIR.glob("*.py"):
        src = py.read_text(encoding="utf-8")
        for banned in ("datetime.now", "datetime.utcnow", "time.time(", "uuid4", "uuid1", "uuid.uuid"):
            if banned in src:
                offenders.append(f"{py.name}: {banned}")
    assert not offenders, f"wall-clock / uuid usage forbidden in data_gen/: {offenders}"
