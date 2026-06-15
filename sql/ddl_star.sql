-- Ocean Freight Forwarder — BigQuery star-schema DDL (Phase 5 / WH-01).
-- Provenance: 05-02-PLAN.md Task 2; 05-RESEARCH.md § "Idempotent dataset +
-- partitioned/clustered fact DDL"; 05-CONTEXT.md D-04/D-04a/D-04b.
--
-- DESIGN (defended):
--   * Native tables (NOT external) — load once into native storage for cheap,
--     fast OLAP scans (D-04). External tables read GCS at query time and are slower.
--   * Star schema, flat dimensions — columnar economics on BigQuery: storage is
--     cheap, unused columns prune for free, joins are comparatively expensive, so
--     snowflaking does not pay off (CLAUDE.md star-vs-snowflake; m2-star-vs-snowflake).
--   * Facts PARTITION BY dt (a DATE column, NOT a TIMESTAMP — Pitfall 4). dt is the
--     leg origin-departure date / port-call arrival date already materialized by the
--     Silver layer (silver/derive.py), so partition pruning is the biggest cost lever
--     for the temporal use cases (UC1 ETA reliability over time, UC2 dwell trend).
--   * Facts CLUSTER BY the high-selectivity FKs each use case filters on (<=4 keys,
--     D-04a). Cluster-key choice per fact is the planner's call within that rule:
--       - fact_voyage_leg: origin_unlocode, dest_unlocode, vessel_imo
--         (UC1 groups schedule reliability by lane (origin,dest) and joins vessel->carrier)
--       - fact_port_call:  unlocode, vessel_imo
--         (UC2 trends dwell/turnaround by port; vessel is the secondary drill-down)
--   * Explicit column types mirror the Silver fact/dim dicts exactly so the Parquet
--     load maps cleanly with no autodetect surprises (Pitfall 3 / D-04). Types:
--     int64->INT64, float64->FLOAT64, date->DATE, timestamp->TIMESTAMP,
--     string->STRING, bool->BOOL. schedule_delta is NULLABLE FLOAT64 (None-on-
--     unmatched-lane, Pitfall 3). effective_to=9999-12-31 is a DATE sentinel (Pitfall 5).
--   * Every statement is CREATE ... IF NOT EXISTS — re-running this file is a no-op
--     (idempotent, ETL-04 criterion 5).
--
-- Apply with:  make ddl   (bq query --use_legacy_sql=false < sql/ddl_star.sql)

-- --------------------------------------------------------------------------- --
-- Dataset (US location to match the US multi-region Bronze/Silver bucket, D-04a).
-- A cross-region load from a US bucket into a non-US dataset errors; keep both US.
-- --------------------------------------------------------------------------- --
CREATE SCHEMA IF NOT EXISTS `data-architecture-msds683.ofa_star`
  OPTIONS(location="US");

-- --------------------------------------------------------------------------- --
-- Facts (date-partitioned + clustered native tables, WH-01).
-- --------------------------------------------------------------------------- --

-- fact_voyage_leg — mirrors silver/derive.py::_voyage_leg_row column order/types.
CREATE TABLE IF NOT EXISTS `data-architecture-msds683.ofa_star.fact_voyage_leg` (
  vessel_imo      STRING,
  origin_unlocode STRING,
  dest_unlocode   STRING,
  transit_hours   FLOAT64,
  distance_nm     FLOAT64,
  schedule_delta  FLOAT64,                 -- NULLABLE (None on unmatched lane, Pitfall 3)
  dt              DATE,                     -- partition key: origin-departure date (Pitfall 4)
  provenance      STRING
)
PARTITION BY dt
CLUSTER BY origin_unlocode, dest_unlocode, vessel_imo;   -- 3 keys (<=4, D-04a)

-- fact_port_call — mirrors silver/derive.py::_port_call_row column order/types.
CREATE TABLE IF NOT EXISTS `data-architecture-msds683.ofa_star.fact_port_call` (
  vessel_imo   STRING,
  unlocode     STRING,
  arrival_ts   TIMESTAMP,                   -- measure, NOT the partition key (Pitfall 4)
  departure_ts TIMESTAMP,                   -- measure, NOT the partition key (Pitfall 4)
  lat          FLOAT64,
  lon          FLOAT64,
  dt           DATE,                         -- partition key: arrival date (Pitfall 4)
  provenance   STRING
)
PARTITION BY dt
CLUSTER BY unlocode, vessel_imo;            -- 2 keys (<=4, D-04a)

-- --------------------------------------------------------------------------- --
-- Dimensions (explicit schemas, D-04). SCD2 = dim_vessel/dim_carrier; SCD1 =
-- dim_port/dim_lane. Column order/types mirror silver/conform.py exactly.
-- --------------------------------------------------------------------------- --

-- dim_vessel (SCD2) — IMO natural key, tracked attr vessel_name.
CREATE TABLE IF NOT EXISTS `data-architecture-msds683.ofa_star.dim_vessel` (
  surrogate_key  INT64,
  imo            STRING,
  vessel_name    STRING,
  effective_from DATE,
  effective_to   DATE,                       -- 9999-12-31 open sentinel (Pitfall 5)
  is_current     BOOL,
  row_hash       STRING,
  provenance     STRING
);

-- dim_carrier (SCD2) — SCAC natural key, tracked attr carrier_name; provenance synthetic.
CREATE TABLE IF NOT EXISTS `data-architecture-msds683.ofa_star.dim_carrier` (
  surrogate_key  INT64,
  scac           STRING,
  carrier_name   STRING,
  effective_from DATE,
  effective_to   DATE,                       -- 9999-12-31 open sentinel (Pitfall 5)
  is_current     BOOL,
  row_hash       STRING,
  provenance     STRING
);

-- dim_port (SCD1) — UN/LOCODE natural key, WPI centroid; provenance real.
CREATE TABLE IF NOT EXISTS `data-architecture-msds683.ofa_star.dim_port` (
  surrogate_key INT64,
  unlocode      STRING,
  lat           FLOAT64,
  lon           FLOAT64,
  provenance    STRING
);

-- dim_lane (SCD1) — lane_key natural key; provenance real.
-- CR-01: the load path produces FIVE columns (dags SCHEMAS["dim_lane"] +
-- silver SILVER_SCHEMAS["dim_lane"], with conform.conform_dim_lane passing through
-- the _lanes_dataframe() origin_unlocode/dest_unlocode columns). The committed DDL
-- (the M4 deliverable) must mirror that 5-column load contract EXACTLY so the
-- Parquet load maps cleanly and the served dim_lane is the table this DDL defines
-- (no CREATE_IF_NEEDED divergence between a 3-col DDL table and a 5-field load).
CREATE TABLE IF NOT EXISTS `data-architecture-msds683.ofa_star.dim_lane` (
  surrogate_key   INT64,
  lane_key        STRING,
  origin_unlocode STRING,
  dest_unlocode   STRING,
  provenance      STRING
);

-- --------------------------------------------------------------------------- --
-- operated_by — synthetic vessel->carrier bridge (D-09); carrier attribution for UC1.
-- --------------------------------------------------------------------------- --
CREATE TABLE IF NOT EXISTS `data-architecture-msds683.ofa_star.operated_by` (
  vessel_imo   STRING,
  carrier_scac STRING,
  provenance   STRING
);

-- --------------------------------------------------------------------------- --
-- SCD2 staging tables (CR-02/CR-03). The SCD2 dims (dim_vessel/dim_carrier) are now
-- loaded EXCLUSIVELY via staging->MERGE (the WRITE_TRUNCATE-of-dim overwrite tasks
-- were removed, eliminating the data race + the no-op MERGE). load_staging_dim_*
-- WRITE_TRUNCATEs the full Silver SCD2 snapshot into these staging tables; the
-- merge_dim_* MERGE then upserts staging -> the persistent dim. The operator's
-- CREATE_IF_NEEDED would also create them, but declaring them here keeps the
-- committed DDL the single source of truth (mirrors dim_vessel/dim_carrier columns).
-- --------------------------------------------------------------------------- --
CREATE TABLE IF NOT EXISTS `data-architecture-msds683.ofa_star.stg_dim_vessel` (
  surrogate_key  INT64,
  imo            STRING,
  vessel_name    STRING,
  effective_from DATE,
  effective_to   DATE,
  is_current     BOOL,
  row_hash       STRING,
  provenance     STRING
);

CREATE TABLE IF NOT EXISTS `data-architecture-msds683.ofa_star.stg_dim_carrier` (
  surrogate_key  INT64,
  scac           STRING,
  carrier_name   STRING,
  effective_from DATE,
  effective_to   DATE,
  is_current     BOOL,
  row_hash       STRING,
  provenance     STRING
);
