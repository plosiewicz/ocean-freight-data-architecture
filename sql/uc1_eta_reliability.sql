-- UC1 — ETA reliability & delay (WH-02, demo surface D-05; no BI tool).
-- Provenance: 05-04-PLAN.md Task 1; 05-RESEARCH.md § "UC1 — ETA reliability";
-- 05-CONTEXT.md D-05 (versioned SQL) / D-02b (carrier attribution from operated_by).
--
-- QUESTION (the freight-forwarder analytical use case):
--   "By carrier, lane, and port-pair, how reliable is the schedule, and how large
--    is the average delay?"  Reliability % + avg schedule_delta over fact_voyage_leg.
--
-- schedule_delta = actual_transit_hours - proforma_transit_hours (silver/derive.py).
--   NEGATIVE  => the real leg was FASTER than the synthetic proforma (early).
--   POSITIVE  => the real leg was SLOWER than the proforma (late).
-- The D-02 data-prep added US->US proforma lanes so schedule_delta is no longer the
-- structurally-dead column WR-01 flagged: it now populates against the real US->US
-- AIS legs (88/88 live), making this question answerable.
--
-- ON-TIME THRESHOLD (defended choice): a leg is "on time" when schedule_delta <= 24h,
--   i.e. it arrived no more than one day later than the proforma. 24h is the
--   conventional single-day SLA grace window for ocean transit; legs that beat the
--   proforma (negative delta) count as on-time. Tune the 24.0 literal to change the SLA.
--
-- CARRIER ATTRIBUTION (A3 bridge, D-02b): AIS carries no operator field, so the
--   vessel->carrier edge is the synthetic `operated_by` bridge (vessel_imo ->
--   carrier_scac) landed in Plan 01; we join it to dim_carrier for the carrier label.
--
-- Run with:  bq query --use_legacy_sql=false < sql/uc1_eta_reliability.sql

SELECT
  c.scac                                                        AS carrier_scac,
  c.carrier_name                                                AS carrier_name,
  f.origin_unlocode                                             AS origin_unlocode,
  f.dest_unlocode                                               AS dest_unlocode,
  CONCAT(f.origin_unlocode, '-', f.dest_unlocode)               AS lane_key,
  COUNT(*)                                                      AS legs,
  ROUND(AVG(f.schedule_delta), 2)                               AS avg_delay_hours,
  ROUND(
    SAFE_DIVIDE(COUNTIF(f.schedule_delta <= 24), COUNT(*)) * 100, 1
  )                                                             AS on_time_pct
FROM `data-architecture-msds683.ofa_star.fact_voyage_leg` AS f
-- Resolve the operating vessel to its current dim_vessel record (SCD2).
JOIN `data-architecture-msds683.ofa_star.dim_vessel` AS v
  ON v.imo = f.vessel_imo
 AND v.is_current
-- Carrier attribution via the A3 bridge (vessel_imo -> carrier_scac), then dim_carrier.
JOIN `data-architecture-msds683.ofa_star.operated_by` AS ob
  ON ob.vessel_imo = f.vessel_imo
JOIN `data-architecture-msds683.ofa_star.dim_carrier` AS c
  ON c.scac = ob.carrier_scac
 AND c.is_current
-- dim_lane ENRICHES the (origin,dest) pair with its conformed surrogate when one
-- exists. It is a LEFT JOIN by design: dim_lane is conformed from the synthetic
-- INTERNATIONAL proforma lanes (CNSHA-US*, etc.), but the only legs with a populated
-- schedule_delta are the real US->US AIS legs (USNYC-USSAV, ...). An INNER join here
-- would drop every answerable row (the lane is not in dim_lane), so the analytic lane
-- is the leg's own (origin,dest) pair materialized above; dim_lane is supplementary.
LEFT JOIN `data-architecture-msds683.ofa_star.dim_lane` AS l
  ON l.lane_key = CONCAT(f.origin_unlocode, '-', f.dest_unlocode)
-- Only legs whose schedule_delta is populated (a proforma lane matched) are answerable.
WHERE f.schedule_delta IS NOT NULL
GROUP BY carrier_scac, carrier_name, origin_unlocode, dest_unlocode, lane_key
ORDER BY legs DESC, avg_delay_hours;
