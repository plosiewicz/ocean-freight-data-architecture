-- Ocean Freight Forwarder — SCD2 MERGE for dim_vessel (Phase 5 / ETL-03).
-- Provenance: 05-03-PLAN.md Task 1; 05-RESEARCH.md § "SCD2 MERGE" + Pitfall 5;
-- mirrors silver/conform.py::_apply_scd2_reload (the content-hash SCD2 logic).
--
-- DESIGN (defended):
--   * Natural key = imo (IMO 7-digit, gated by valid_imo upstream). Tracked attr =
--     vessel_name -> row_hash in the Silver SCD2 snapshot (silver/conform.py).
--   * TWO statements, not one: BQ MERGE matches a key once and cannot both close the
--     old version AND insert the new one for the same key (Pitfall 5). So:
--       Step 1 (MERGE): close the CURRENT row whose row_hash changed
--                       (is_current=FALSE, effective_to=@run_date).
--       Step 2 (INSERT): add the new/changed version, guarded by NOT EXISTS so a
--                       no-change re-run inserts nothing (idempotent, ETL-04).
--   * @run_date is the deterministic slice max-event-date passed as a TYPED DATE
--     query parameter (BigQueryInsertJobOperator queryParameters) — never the
--     wall-clock today() builtin (Pitfall 5 / threat T-05-09) and never
--     string-interpolated (threat T-05-07).
--   * effective_to open sentinel = DATE "9999-12-31" (A5 / Pitfall 5) — a DATE, not
--     NULL, so the column stays a single dtype; current rows are found by is_current.
--
-- LOAD TOPOLOGY (CR-02/CR-03 fixed): dim_vessel is now loaded EXCLUSIVELY by this
-- staging->MERGE path. The DAG WRITE_TRUNCATEs the full Silver SCD2 snapshot into
-- stg_dim_vessel (load_staging_dim_vessel), then runs this MERGE (merge_dim_vessel)
-- to upsert staging -> the persistent dim_vessel. The prior WRITE_TRUNCATE-of-dim
-- "overwrite" task was REMOVED: it raced this MERGE on the same table (CR-03) and
-- made the MERGE a structural no-op against its own overwritten output (CR-02). With
-- the overwrite gone, the MERGE is the genuine, idempotent, SCD2-demonstrating load —
-- a first MERGE into a clean dim INSERTs all current versions; a no-change re-run is
-- a no-op (NOT-EXISTS guard); a tracked-attr change closes the old row + inserts a
-- new version with a fresh unique surrogate (Step 2 below).
--
-- Run via BigQueryInsertJobOperator(configuration={"query": {... queryParameters:
--   [{name:"run_date", parameterType:{type:"DATE"}, parameterValue:{value:"{{ ds }}"}}]}}).

-- Step 1: close current rows whose tracked attributes changed (row_hash differs).
MERGE `data-architecture-msds683.ofa_star.dim_vessel` AS t
USING `data-architecture-msds683.ofa_star.stg_dim_vessel` AS s
ON t.imo = s.imo AND t.is_current
WHEN MATCHED AND t.row_hash != s.row_hash THEN
  UPDATE SET is_current = FALSE, effective_to = @run_date;

-- Step 2: insert new versions for brand-new keys OR changed keys. The NOT EXISTS
-- guard (any version already carrying this imo+row_hash) makes a no-change re-run a
-- no-op (idempotent, ETL-04 / Pitfall 5).
--
-- CR-02 (surrogate-key collision fix): do NOT carry s.surrogate_key from staging.
-- conform.assign_surrogate recomputes a dense 1-based surrogate every run by sorting
-- the CURRENT natural keys, so a new version's staging surrogate would collide with a
-- closed row's surrogate already in the dim (the surrogate would no longer be unique
-- per version, breaking any join keyed on it). Instead, generate a FRESH unique
-- surrogate above the current MAX: MAX(surrogate_key) over the persistent dim +
-- a dense ROW_NUMBER over the rows actually being inserted (ordered by imo for a
-- deterministic assignment). This keeps surrogate_key unique across all versions.
INSERT INTO `data-architecture-msds683.ofa_star.dim_vessel`
  (surrogate_key, imo, vessel_name, effective_from, effective_to, is_current, row_hash, provenance)
SELECT
  (SELECT COALESCE(MAX(surrogate_key), 0)
     FROM `data-architecture-msds683.ofa_star.dim_vessel`)
    + ROW_NUMBER() OVER (ORDER BY s.imo)                       AS surrogate_key,
  s.imo, s.vessel_name,
  @run_date, DATE "9999-12-31", TRUE, s.row_hash, s.provenance
FROM `data-architecture-msds683.ofa_star.stg_dim_vessel` s
WHERE NOT EXISTS (
  SELECT 1 FROM `data-architecture-msds683.ofa_star.dim_vessel` d
  WHERE d.imo = s.imo AND d.row_hash = s.row_hash
);
