"""JSONL read/write primitives.

Canonical JSONL sink for all data_gen/* generators: one JSON object per line,
UTF-8, ``ensure_ascii=False``, LF endings, trailing LF, NO ``sort_keys``.
Byte-stability comes from the fixed key-insertion order in each generator's
canonical row constructor (P-4), not from sorting here.

Provenance: copied verbatim from /Users/plosiewicz/Desktop/supply-chain/lib/jsonl.py
(Brambles prior art); 03-PATTERNS.md § JSONL sink (D-10).
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator
from pathlib import Path


def write_jsonl(path: Path, rows: Iterable[dict]) -> int:
    """Write each ``row`` as a single JSON line to ``path`` (UTF-8).

    Returns the number of rows written. ``path``'s parent directory must exist;
    we do not auto-create it (the generator owns dataset/ provisioning).
    """
    count = 0
    with open(path, "w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False))
            fh.write("\n")
            count += 1
    return count


def read_jsonl(path: Path) -> Iterator[dict]:
    """Yield one parsed dict per non-blank line in ``path`` (UTF-8).

    Blank / whitespace-only lines are skipped silently. On a malformed line we
    re-raise ``json.JSONDecodeError`` with the 1-based line number prefixed so
    the caller can locate the bad row.
    """
    with open(path, encoding="utf-8") as fh:
        for lineno, raw in enumerate(fh, start=1):
            line = raw.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError as exc:
                raise json.JSONDecodeError(f"line {lineno}: {exc.msg}", exc.doc, exc.pos) from None
