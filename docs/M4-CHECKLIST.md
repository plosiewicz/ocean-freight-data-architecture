# M4 — GitHub Repo Contents & Access Checklist (DEL-02)

> **Purpose:** A single reviewer-facing checklist that (a) enumerates what this repo
> contains by area, (b) states exactly which credentials a reviewer must supply to run
> the **optional live path** (and confirms the **default demo path needs none**), and
> (c) records the **no-committed-secrets** contract that is mechanically gate-enforced.
> Mirrors the `README.md` "Repo notes" + M2 doc-table format.

This is the M4 deliverable evidence. A reviewer can read this file top to bottom and
confirm DEL-02 completeness: repo contents present, access requirements documented, no
credentials committed, and synthetic data reproducible-from-clone (see
[`RUN-FROM-CLONE.md`](RUN-FROM-CLONE.md)).

---

## (a) Repo contents by area

| Area | Path | What it holds |
|------|------|---------------|
| Ingestion (Bronze) | `ingest/` | Real-source pulls: `pull_ais.py` (bounded 4-port 2024 AIS slice), `pull_reference.py` (UN/LOCODE · WPI · chokepoints), `pull_priors.py` (LSCI · LPI · Comtrade) |
| Synthetic generation | `data_gen/`, `scripts/generate.py` | Seeded Faker/NumPy generators → byte-stable JSONL (schedules, bookings, container events) |
| Conformance (Silver) | `silver/` | Pure transforms: `identity.py` (MMSI→IMO), `geofence.py` + `derive.py` (port-calls / voyage-legs), `conform.py` (SCD1/SCD2 dims), `land_silver.py` (Bronze→Silver landing) |
| Warehouse SQL (Gold / BigQuery) | `sql/` | `ddl_star.sql` (star DDL), `merge_dim_*.sql`, `uc1_eta_reliability.sql`, `uc2_dwell_trend.sql` |
| Graph queries (Gold / ArangoDB) | `aql/` | `uc3_chokepoint_share.aql`, `uc3_closure_unreachable.aql`, `uc3_reroute_impact.aql`, `uc4_reroute_shortest_path.aql`, plus `*.explain.txt` index-defense artifacts |
| Graph analytics runners | `analytics/` | `run_criticality.py` (GAE + NetworkX fallback), `uc3_closure.py`, `uc4_reroute.py`, `snapshot_uc.py` (credential-free freeze source) |
| Shared libraries | `lib/` | `arango_client.py` (env-driven TLS-on cluster client), `graph_loader.py`, `graph_queries.py`, `gcs.py`, `jsonl.py`, `seeds.py` |
| Orchestration (Airflow) | `dags/` | `ofa_warehouse_dag.py` — the one Composer-portable warehouse DAG (load_bq + load_arango legs + verify) |
| Verb runner | `Makefile` | `generate`, `verify`, `verify-uc`, `verify-cluster`, `freeze`, `load-bq`, `load-arango`, `refreeze-sha256`, `ddl` |
| Ship-gate | `scripts/verify.py` | The full fail-fast gate ladder (exit codes 0..20), incl. `gate_sha256` (determinism) and `gate_credential_audit` (no committed secrets, exit 20) |
| Frozen demo snapshots | `data/golden/` | `uc1`..`uc4` `*.golden.json` — byte-stable, credential-free UC answers the demo reads by default (DEL-01 failure-proofing) |
| Determinism manifest | `synthetic.sha256` | Committed sha256 digests of the generated synthetic JSONL — the byte-identical reproducibility anchor |
| Deck source | `docs/deck/` | M1/M2 (and later M3/Final) deck-source `.md` — the source of truth for the shared Google Slides deck |
| Demo notebook | `docs/demo.ipynb` | (DEL-01, Wave 2) four-UC notebook reading the frozen `data/golden/` snapshots |
| Project guidance | `CLAUDE.md`, `README.md` | Prescriptive stack, version pins, architecture overview |

**Intentionally NOT committed** (see `.gitignore`): bulk sample data (`samples/`), bulk
pipeline data (`data/*` except the allow-listed `data/golden/*.golden.json`), the real
`.env` and any `*.env*` / `*.key` / `secrets.*`, GSD planning artifacts (`.planning/`),
and Python/Airflow runtime artifacts.

---

## (b) Access checklist — what a reviewer must set to run

### Default demo path — NO credentials required

- [x] The demo notebook (`docs/demo.ipynb`) reads the **frozen `data/golden/uc*.golden.json`
  snapshots by default**. These are committed, credential-free (counts/floats/strings only),
  and byte-stable — so the demo runs end-to-end from a fresh clone with **no GCP and no
  ArangoDB access**. This is the failure-proof default (DEL-01).
- [x] The synthetic-data reproducibility proof (`make generate` → `make verify` →
  matching `synthetic.sha256`) is **fully local** — it touches neither cloud. See
  [`RUN-FROM-CLONE.md`](RUN-FROM-CLONE.md).

### Optional LIVE path — reviewer-supplied credentials

To exercise the "look, it's real" live aside (hit BigQuery / the ArangoDB cluster
directly), a reviewer sets the following. **Copy `.env.template` to `.env`** (the real
`.env` is gitignored and must never be committed) and fill in real values:

| What | How |
|------|-----|
| ArangoDB cluster | `ARANGO_URL`, `ARANGO_USERNAME`, `ARANGO_PASSWORD`, `ARANGO_DATABASE` in `.env` (TLS-on HTTPS endpoint from the cluster dashboard; `ARANGO_GRAPH=ocean_network` is a non-secret default). Smoke-test with `make verify-cluster`. |
| BigQuery | **Application Default Credentials** (ADC) authed to project `data-architecture-msds683` — no key file. Confirm `~/.config/gcloud/application_default_credentials.json` exists, or run `gcloud auth application-default login`. |
| Comtrade (optional) | `COMTRADE_API_KEY` is optional; the keyless public preview tier suffices. Leave blank unless higher rate limits are needed. |

Environment variable **names** only are listed here — no real values appear in this repo.

---

## (c) Credential audit — the no-committed-secrets contract (gate-enforced)

The "no secret may cross the git-tracked → public-GitHub boundary" rule (threat T-07-05)
is **mechanically enforced**, not just documented:

- **`gate_credential_audit` (exit code 20)** in `scripts/verify.py` runs as the last gate
  of `make verify`. It runs `git ls-files` and **fails the ship-gate** if any tracked file
  matches the secret patterns `.gitignore` already excludes — a real `.env`, any `*.env*`,
  `*.key`, or `secrets.*`. On a violation it prints the offending **path only**, never the
  secret value (threat T-07-08).
- It then audits **`.env.template`** to assert every value is a **placeholder** (empty or an
  obvious placeholder token) — a real-looking JWT/password/credential value in the template
  fails the gate (threat T-07-06).
- The `.gitignore` secret-exclusion + template-allow-list contract it mirrors:

  ```gitignore
  .env
  .env.*
  *.env*
  *.key
  secrets.*
  !.env.template       # ...but DO commit the non-secret template (placeholders only)
  ```

- `.env.template` ships **placeholders only** (see its header: "Copy this file to `.env`
  and fill in real values. The real `.env` is GITIGNORED ... and MUST NEVER be committed").

To check the contract locally: `make verify` (full ladder) — a clean repo prints a
`[CITE] credential audit: 0 credential paths tracked ...` line and exits 0; a committed
secret pattern fails with exit 20 and the offending path.

---

## DEL-02 completeness checklist

- [x] Repo contents enumerated by area (section a).
- [x] Access checklist documents the live-path env vars; default demo path needs no credentials (section b).
- [x] No-committed-secrets contract is gate-enforced (`gate_credential_audit`, exit 20) and the `.env.template` placeholder rule is stated (section c).
- [x] Reproducible-from-clone synthetic-data proof documented in [`RUN-FROM-CLONE.md`](RUN-FROM-CLONE.md).
