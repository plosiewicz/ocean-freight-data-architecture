"""Pure, deterministic synthetic data generators (ING-03, ING-04).

Each module is a PURE function of the central ``lib.seeds.SEED`` (+ a per-entity
offset): same seed -> byte-identical JSONL (the D-12 determinism contract). The
generators NEVER touch the network or wall-clock and NEVER emit a random UUID —
all timestamps derive from seeded quarter-window arithmetic and all ids are
deterministic counters. Landing the generated JSONL into GCS Bronze is a
SEPARATE idempotent step (scripts/load_bronze.py); generators stay pure.

The synthetic network is conditioned on the real priors landed in Bronze
(``data_gen.conditioning``): lane plausibility from LSCI x LSCI x Comtrade O-D,
per-country delay distributions from World Bank LPI (ING-04). Priors are
weights/means only — never promoted to facts (D-13).

Provenance: Brambles prior art generator/loader split
(/Users/plosiewicz/Desktop/supply-chain/data_gen); 03-RESEARCH.md § Determinism
Pattern; 03-PATTERNS.md § data_gen assignments.
"""
