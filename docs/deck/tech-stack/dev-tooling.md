# Dev tooling — Make · pytest · Git/GitHub

**Layer:** the development/reproducibility tooling around the pipeline. (Supporting cast — but the
brief's "tech stack" slide and Q&A may touch them.)

## What they do & their role
- **Make (`Makefile`)** — verb-script entrypoints: `make bronze | silver | warehouse | load-arango |
  freeze | demo | verify`. One memorable command per stage; targets shell to `python -m <module>` or
  to `bq`/`airflow`. This is the demo-driving surface and the reproducible run contract.
- **pytest (`tests/`)** — the test suite that pins the business logic: `test_geofence.py`,
  `test_derive.py`, `test_conditioning.py`, `test_arango_load.py`, `test_cross_store.py`,
  `test_dag.py`, and the UC3/UC4 anti-degeneracy tests. The pure transforms are tested **offline**
  (no cloud needed), which is what lets us trust the numbers on stage.
- **Git / GitHub** — version control and the M4 deliverable (the repo + its checklist). Versioned SQL
  (`sql/`), AQL (`aql/`), and frozen goldens (`data/golden/`) make every result auditable and citable.

## Why these are the best options here
- **Make** is universal, zero-install, and the right altitude for "one command per pipeline stage" —
  it makes the demo reproducible by a teammate without memorizing module paths.
- **pytest** is the Python testing default; its offline unit tests on the pure geo-fence/derive/
  conditioning functions are *why* the demo numbers are trustworthy and non-degenerate.
- **Git/GitHub** is the assignment's M4 artifact and the audit trail for every design decision.

## Alternatives considered
| Alternative | Why not here | When you'd pick it |
|---|---|---|
| Taskfile / Just | Equivalent task runners; Make is universal and zero-install | Team preference for a modern runner |
| unittest | pytest's fixtures/parametrization are more ergonomic | Stdlib-only constraint |
| A shell-script "pipeline" instead of tests | Doesn't pin business logic; can't assert non-degeneracy | Throwaway scripts |

## Likely Q&A
- *"How do you know the demo numbers are right?"* — the pure transforms are unit-tested offline, the
  results are frozen as goldens, and the ship-gate asserts *direction* (reroute delta > 0, closed
  reachability < open) so a degenerate all-zero result can't silently render.
- *"How does a teammate reproduce it?"* — `make bronze → silver → warehouse → load-arango → freeze →
  demo`; seeded synthetic + idempotent loads make it byte-identical.
