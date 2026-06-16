# Ocean Freight Forwarder Data Architecture (MSDS 683) — verb-runner.
# Provenance: .planning/phases/03-ingestion-bronze/03-PLAN.md Task 1; Brambles Makefile idiom.
# Each target shells to `python -m <module>` (Bronze/Silver) or to bq/airflow
# (warehouse). The Airflow/DAG gate the Phase-3 header deferred is now OPEN in
# Phase 5: this project uses PLAIN Apache Airflow, not Cloud Composer (D-01) —
# the DAG (Plan 03) stays Composer-portable (standard operators only, D-01a).
#
# D-04: single Bronze bucket, one prefix per tier. Override on the CLI, e.g.
#   make load-bronze BRONZE_BUCKET=gs://my-other-bucket
BRONZE_BUCKET ?= gs://data-architecture-msds683-bronze

PYTHON ?= python

.PHONY: pull-ais pull-reference pull-priors generate load-bronze verify bronze conform derive silver \
        ddl load-bq warehouse refreeze-sha256 load-arango verify-cluster verify-uc

# --- Warehouse config (Phase 5) ---
BQ_PROJECT ?= data-architecture-msds683
BQ_DATASET ?= ofa_star
DAG_ID     ?= ofa_warehouse
DAG_DATE   ?= 2024-01-31

# --- Source pulls (implementing modules land in Wave 2: 03-02..03-04) ---
pull-ais:
	$(PYTHON) -m ingest.pull_ais

pull-reference:
	$(PYTHON) -m ingest.pull_reference

pull-priors:
	$(PYTHON) -m ingest.pull_priors

# --- Synthetic generation (module lands in a later plan) ---
generate:
	$(PYTHON) -m scripts.generate --seed 20240614

# --- Bronze landing (idempotent GCS upload; module lands in a later plan) ---
load-bronze:
	$(PYTHON) -m scripts.load_bronze --bucket $(BRONZE_BUCKET)

# --- Ship-gate (this plan: scripts/verify.py skeleton, honestly red until inputs land) ---
verify:
	$(PYTHON) -m scripts.verify

# --- Focused LIVE UC anti-degeneracy gate (exit 19) for fast iteration -----------
# Runs ONLY gate_uc_anti_degeneracy against the managed ArangoDB cluster (.env creds,
# TLS-on): it EXECUTES UC3 reroute-impact (SUEZ/PANAMA detour, delta>0), the GIBRALTAR
# genuine-unreachability drop, and the UC4 weighted reroute (delta>0), then exits the
# gate's code (0 = non-degenerate, 19 = degenerate). `make verify` still runs the full
# 0..19 ladder; this is the smoke target for iterating on the graph/UC layer alone
# (mirrors `make verify-cluster`). The DAG verify task also gates on the same logic.
verify-uc:
	$(PYTHON) -c "import sys; from scripts.verify import gate_uc_anti_degeneracy, EXIT_OK, EXIT_UC_DEGENERATE; sys.exit(EXIT_OK if gate_uc_anti_degeneracy() else EXIT_UC_DEGENERATE)"

# --- Chained orchestrator: full Bronze pipeline in dependency order ---
bronze: pull-reference pull-priors pull-ais generate load-bronze verify

# --- Silver: Bronze -> conform + derive -> idempotent silver/ landing (ETL-01) ---
# conform lands the four dims (snapshots, no dt=); derive lands the two facts
# (dt= partitioned). Both write-once via upload_if_absent (D-07/D-08).
conform:
	$(PYTHON) -m silver.land_silver --bucket $(BRONZE_BUCKET) --step conform

derive:
	$(PYTHON) -m silver.land_silver --bucket $(BRONZE_BUCKET) --step derive

# --- Chained orchestrator: conform -> derive -> verify (mirrors bronze:) ---
silver: conform derive verify

# --- Warehouse (Phase 5): BigQuery star — DDL bootstrap, load, analytics ---
# ddl: create the ofa_star dataset (US) + partitioned/clustered native fact/dim
# tables from versioned SQL. CREATE ... IF NOT EXISTS -> idempotent (ETL-04 crit 5).
ddl:
	bq query --use_legacy_sql=false < sql/ddl_star.sql

# load-bq: run the one Airflow DAG (Plan 03) end-to-end against real GCS/BQ —
# stage_conform -> load_staging -> merge/overwrite -> verify. Plain Airflow (D-01),
# Composer-portable (D-01a). The DAG file itself lands in Plan 03; the target is
# authored here. `airflow dags test` runs a single creds-backed run, no scheduler.
#
# ZERO-INSTALL importability: `airflow dags test` runs each task in a SUBPROCESS
# whose sys.path excludes the repo root, so the project packages (silver/, lib/, ...)
# would NOT import. The DAG bootstraps the repo root onto sys.path at parse time
# (dags/ofa_warehouse_dag.py), so NO `pip install -e .` is required here. Keep this
# install-free so the target is portable (local + Composer) — tests/test_dag.py
# guards the bootstrap.
# GCP auth: local Airflow has no `google_cloud_default` connection (Composer auto-
# provides it). Point it at Application Default Credentials via an env-var connection
# (empty google-cloud-platform:// URI → ADC), so the Google operators authenticate as
# the compute SA. The DAG still uses the default conn id, so it stays Composer-portable.
load-bq:
	AIRFLOW__CORE__DAGS_FOLDER=$(PWD)/dags AIRFLOW_HOME=$(PWD)/.airflow \
	AIRFLOW_CONN_GOOGLE_CLOUD_DEFAULT='google-cloud-platform://' \
	AIRFLOW__CORE__LOAD_EXAMPLES=False \
		airflow dags test $(DAG_ID) $(DAG_DATE)

# warehouse: full warehouse path in dependency order (mirrors the silver: chain).
warehouse: ddl load-bq verify

# --- Graph sink (Phase 6, ETL-05): the SECOND sink off the SAME silver/ staging ---
# verify-cluster: front-loaded connection smoke — prove the gitignored .env creds
# reach the managed ArangoDB cluster over TLS BEFORE the live load runs. Prints a
# diagnostic (version, cluster topology, RTT, whether ocean_network already exists);
# never prints the password/JWT (T-06-01/T-06-03). Run this first at the checkpoint.
verify-cluster:
	$(PYTHON) -m scripts.verify_cluster

# load-arango: project the conformed Silver dims + the synthetic lane network into
# the managed ocean_network graph via idempotent python-arango UPSERT by deterministic
# _key (UN/LOCODE/IMO/SCAC, D-11). This is graph_loader.load_graph — the SAME entrypoint
# the DAG load_arango @task calls (D-06a) — so `make load-arango` and the DAG are one
# code path. Re-runnable (ETL-04 parity): a second run UPSERTs the same _keys, leaving
# the graph unchanged. Reads the SAME silver/ Parquet the BQ load reads ("one transform,
# two sinks", ETL-05). Connects over HTTPS via lib.arango_client (env creds, TLS-on).
load-arango:
	$(PYTHON) -c "from lib.graph_loader import load_graph; load_graph(bucket='$(BQ_PROJECT)-bronze')"

# refreeze-sha256: re-write the synthetic.sha256 determinism manifest from freshly
# generated output (D-02b convenience — run after a generator change, then commit
# synthetic.sha256). `make generate` (scripts/generate.py) ALWAYS rewrites the
# manifest as part of its run, so this is the named D-02b entry point + a guard.
refreeze-sha256: generate
	@echo "synthetic.sha256 refrozen by 'make generate' — review the diff and commit it (D-02b)."
