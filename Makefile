# Ocean Freight Forwarder Data Architecture (MSDS 683) — verb-runner.
# Provenance: .planning/phases/03-ingestion-bronze/03-PLAN.md Task 1; Brambles Makefile idiom.
# Each target shells to `python -m <module>`. NO Composer/Airflow/DAG targets here
# (D-08 / D-18 — managed Airflow is deferred to Phase 5).
#
# D-04: single Bronze bucket, one prefix per tier. Override on the CLI, e.g.
#   make load-bronze BRONZE_BUCKET=gs://my-other-bucket
BRONZE_BUCKET ?= gs://data-architecture-msds683-bronze

PYTHON ?= python

.PHONY: pull-ais pull-reference pull-priors generate load-bronze verify bronze conform derive silver

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
