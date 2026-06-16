# Run From Clone — Reproducible Synthetic Data Proof (DEL-02)

> **Purpose:** Document the fresh-clone command sequence that proves the synthetic data
> is **byte-identically reproducible** — and that the proof is **gate-enforced**, not
> asserted. This is the DEL-02 "reproducible-from-clone synthetic data" evidence.
>
> The whole sequence is **fully local** — it touches neither GCP nor the ArangoDB
> cluster, so a reviewer needs **no credentials** to reproduce it.

---

## The command sequence

```bash
# 1. Clone
git clone <repo-url> ocean-freight-data-arch
cd ocean-freight-data-arch

# 2. Install (editable; pins are exact for the determinism anchors)
python -m venv .venv && source .venv/bin/activate
pip install -e .

# 3. Regenerate the synthetic data deterministically (seeded)
make generate          # python -m scripts.generate --seed 20240614

# 4. Prove byte-identity against the committed manifest
make verify            # runs the full gate ladder, incl. gate_sha256 (exit 1 on mismatch)
```

A clean run exits **0** and prints:

```
[OK] sha256 gate: <N> files byte-identical to synthetic.sha256 (criterion 3)
```

Any drift fails fast at `gate_sha256` (exit code **1**) with the offending filename.

---

## Why it is byte-identical (the determinism anchors)

The reproducibility is mechanical because two dependencies are pinned **exactly** in
`pyproject.toml` (not as ranges):

```toml
"Faker==40.1.2",     # Faker output is NOT stable across patch releases — pinned exactly
"numpy==1.26.4",     # default_rng draws are byte-identical only on a shared numpy major
```

Both pins are the deliberate determinism anchors (D-12 / ING-03). Every team member and
every reviewer who installs from `pyproject.toml` gets the same Faker patch and the same
NumPy major, so seeded generation (`--seed 20240614`) produces byte-identical JSONL.

The support libraries (`pyarrow`, `pandas`, `google-cloud-storage`) are relaxed to `>=`
ranges resolved via the Airflow constraints file; they do **not** affect synthetic output
byte-stability — only the two `==` anchors do.

---

## How the gate works (the enforcement)

`gate_sha256` in `scripts/verify.py` is the fresh-clone reproducibility mechanism. It:

1. Reads the committed `synthetic.sha256` digests **into memory** first (so the on-disk
   manifest that `make generate` rewrites can't poison the comparison).
2. Re-runs the generator into a **temporary directory** via a subprocess:
   `python -m scripts.generate --seed <SEED> --out-dir <tmp>`.
3. Computes the sha256 of each regenerated file and **diffs** it against the committed
   digest.
4. On any mismatch → exits `EXIT_SHA_MISMATCH` (**1**) with the offending filename; on full
   match → prints the `[OK] sha256 gate ...` citation.

This is exactly the "fresh clone → `make generate` → matching `synthetic.sha256`" proof.

### Updating the manifest after an intentional generator change

```bash
make refreeze-sha256   # = make generate (which always rewrites synthetic.sha256) + a reminder
# review the synthetic.sha256 diff, then commit it
```

---

## Relationship to the other gates

`make verify` runs the **full** fail-fast ladder (exit codes 0..20). `gate_sha256` is the
first, fully-local gate (the reproducibility proof). Later gates touch GCS / BigQuery / the
ArangoDB cluster and need credentials — but the **synthetic-data reproducibility proof
itself is local and credential-free**, which is the DEL-02 claim this document supports.

The no-committed-secrets contract is the companion DEL-02 gate (`gate_credential_audit`,
exit 20) — see [`M4-CHECKLIST.md`](M4-CHECKLIST.md) section (c).

> No real credential, host, JWT, or password value appears in this document or in the
> command sequence above — only the public seed (`20240614`) and the public project id.
