-- UC2 — port congestion & dwell-time trend (WH-03, demo surface D-05; no BI tool).
-- Provenance: 05-04-PLAN.md Task 1; 05-RESEARCH.md § "UC2 — dwell/turnaround trend";
-- 05-CONTEXT.md D-05 (versioned SQL) / D-02a (wider AIS window gives >=2 dates).
--
-- QUESTION (the freight-forwarder analytical use case):
--   "Per port, how does vessel turnaround / dwell time trend day over day?"
--   Turnaround = TIMESTAMP_DIFF(departure_ts, arrival_ts, HOUR) over fact_port_call,
--   trended by the dt partition (arrival date). The wider AIS window (D-02a, 31 days
--   live) gives the >=2 distinct dates the temporal trend needs.
--
-- The dt partition column is the per-call ARRIVAL date (silver/derive.py, Pitfall 4),
-- so partition pruning bounds the scan when filtering a date range (WH-01 cost lever).
--
-- Run with:  bq query --use_legacy_sql=false < sql/uc2_dwell_trend.sql

SELECT
  p.unlocode                                                    AS unlocode,
  f.dt                                                          AS call_date,
  COUNT(*)                                                      AS calls,
  -- WR-03: compute turnaround in FRACTIONAL hours. TIMESTAMP_DIFF(..., HOUR) truncates
  -- toward zero (a 1.9-hour turnaround reports 1), systematically understating dwell
  -- across the average and flooring the max. Diff in SECOND / 3600.0 keeps the trend
  -- accurate while staying demo-legible (rounded to 2 decimals).
  ROUND(
    AVG(TIMESTAMP_DIFF(f.departure_ts, f.arrival_ts, SECOND) / 3600.0), 2
  )                                                             AS avg_turnaround_hours,
  ROUND(
    MAX(TIMESTAMP_DIFF(f.departure_ts, f.arrival_ts, SECOND) / 3600.0), 2
  )                                                             AS max_turnaround_hours
FROM `data-architecture-msds683.ofa_star.fact_port_call` AS f
-- Join the conformed dim_port so the trend is keyed on the conformed UN/LOCODE.
JOIN `data-architecture-msds683.ofa_star.dim_port` AS p
  ON p.unlocode = f.unlocode
-- WR-03: exclude inverted intervals (departure before arrival) — a mis-ordered call
-- would contribute a negative dwell that silently biases the average/max downward.
WHERE f.departure_ts >= f.arrival_ts
GROUP BY unlocode, call_date
ORDER BY unlocode, call_date;
