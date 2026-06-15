"""IMO 7-digit check-digit validator — pure boolean predicate, never raises.

ETL-01 / CONTEXT D-06: "valid IMO" = exactly 7 digits passing the IMO
check-digit. This is the V5 input-validation gate (threat T-04-01 / T-04-02)
that rejects MMSI values, zero-padding, and typos before an IMO is trusted as
a vessel natural key. It is a non-raising predicate by design — the caller
(``silver/identity.py``) decides drop-vs-keep and counts the drops.

Algorithm (verified across 3 sources): for the first six digits A B C D E F the
check digit G is the units digit of ``7A + 6B + 5C + 4D + 3E + 2F``. Worked
golden example: 9074729 -> 9*7 + 0*6 + 7*5 + 4*4 + 7*3 + 2*2 = 139 -> units
digit 9 = the seventh digit -> valid.

Provenance: 04-RESEARCH.md § Code Examples "IMO check-digit validator" +
Pitfall 2; sources https://gcaptain.com/imo-numbers/ and
https://en.wikipedia.org/wiki/IMO_number (cross-verified, golden case 9074729).
"""

from __future__ import annotations


def valid_imo(imo) -> bool:
    """Return True iff ``imo`` is 7 digits passing the IMO check-digit.

    Coerces any input via ``str(imo).strip()`` and returns False (never raises)
    on non-7-digit or non-numeric input — including ``None``.
    """
    s = str(imo).strip()
    if not (s.isdigit() and len(s) == 7):
        return False
    # WR-06: the all-zero IMO ``0000000`` passes the check-digit arithmetic
    # (0*7+...+0 = 0, units 0 == digit[6] 0) but is a zero-padding sentinel, not a
    # real vessel natural key. Reject it explicitly so an ``IMO0000000`` static
    # message is never admitted as a vessel (D-06 input-validation gate).
    if s == "0000000":
        return False
    digits = [int(c) for c in s]
    weighted = sum(d * w for d, w in zip(digits[:6], (7, 6, 5, 4, 3, 2)))
    return weighted % 10 == digits[6]
