-- Ocean Freight Forwarder — SCD2 MERGE for dim_carrier (Phase 5 / ETL-03).
-- Provenance: 05-03-PLAN.md Task 1; 05-RESEARCH.md § "SCD2 MERGE" + Pitfall 5;
-- mirrors silver/conform.py::_apply_scd2_reload (same logic, scac natural key).
--
-- DESIGN (defended) — identical shape to merge_dim_vessel.sql, scac as natural key:
--   * Natural key = scac (carrier SCAC from data_gen.network.CARRIER_SCACS). Tracked
--     attr = carrier_name -> row_hash in the Silver SCD2 snapshot. provenance=synthetic
--     (carriers are reference-assigned, D-09/D-11).
--   * TWO statements (Pitfall 5): Step 1 MERGE closes the CURRENT row whose row_hash
--     changed; Step 2 NOT-EXISTS-guarded INSERT of the new/changed version (idempotent).
--   * @run_date = deterministic slice max-event-date, TYPED DATE query parameter,
--     never the wall-clock today() builtin (Pitfall 5 / T-05-09) and never
--     string-interpolated (T-05-07).
--   * effective_to open sentinel = DATE "9999-12-31" (A5 / Pitfall 5).
--
-- HONESTY NOTE (D-04): the LIVE load WRITE_TRUNCATEs the authoritative Silver SCD2
-- snapshot; this MERGE is the documented/demo artifact of the named MERGE pattern.

-- Step 1: close current rows whose tracked attributes changed (row_hash differs).
MERGE `data-architecture-msds683.ofa_star.dim_carrier` AS t
USING `data-architecture-msds683.ofa_star.stg_dim_carrier` AS s
ON t.scac = s.scac AND t.is_current
WHEN MATCHED AND t.row_hash != s.row_hash THEN
  UPDATE SET is_current = FALSE, effective_to = @run_date;

-- Step 2: insert new versions for brand-new keys OR changed keys (NOT EXISTS guard
-- = idempotent no-change re-run, ETL-04 / Pitfall 5).
INSERT INTO `data-architecture-msds683.ofa_star.dim_carrier`
  (surrogate_key, scac, carrier_name, effective_from, effective_to, is_current, row_hash, provenance)
SELECT
  s.surrogate_key, s.scac, s.carrier_name,
  @run_date, DATE "9999-12-31", TRUE, s.row_hash, s.provenance
FROM `data-architecture-msds683.ofa_star.stg_dim_carrier` s
WHERE NOT EXISTS (
  SELECT 1 FROM `data-architecture-msds683.ofa_star.dim_carrier` d
  WHERE d.scac = s.scac AND d.row_hash = s.row_hash
);
