# NumPy

**Layer:** seeded random distributions for the synthetic event/weight generation.

## What it does
NumPy's modern `default_rng(seed)` Generator API draws reproducible random numbers. We use it for
every distributional draw in the synthetic layer.

## Role in our project
- `data_gen/` and `data_gen/conditioning.py`: seeded draws for per-leg **delays** (LPI-conditioned
  lognormal — `nprng.lognormal(mean=log(mean), sigma=0.5)`), dwell times, and booking/event volumes.
- A central `SEED` constant + per-entity streams make each generator deterministic and independent —
  re-running yields **byte-identical** output (the `synthetic.sha256` contract).

## Why it's the best option here
- **`default_rng` is the modern, reproducible Generator API** — the right tool for "same seed → same
  bytes," which is the whole point of our synthetic layer (any teammate reproduces the demo exactly).
- **It's already the substrate** under pandas/pyarrow and the scientific Python stack — no new
  dependency, clean interop.
- The conditioning math (normalization, lognormal delay model) is naturally vectorized in NumPy.

## Alternatives considered
| Alternative | Why not here | When you'd pick it |
|---|---|---|
| Python stdlib `random` | Weaker distribution support and a global-state API that's easy to make non-reproducible | Trivial coin-flips |
| SDV / Gretel (statistical synthesizers) | Learn joint distributions from real data — we want *scripted, controlled, deterministic* generators, not learned ones | When you must mimic a real dataset's joint distribution |
| `numpy.random` legacy `RandomState` | Superseded by `default_rng`; the new Generator is the recommended path | Legacy code |

## Likely Q&A
- *"How is the synthetic data reproducible?"* — every draw goes through `numpy.random.default_rng(SEED)`
  with per-entity streams; output is hashed in `synthetic.sha256` so a re-run is provably identical.
- *"Why model delays as lognormal?"* — non-negative, right-skewed (a few long delays), centered on an
  LPI-conditioned mean — a defensible shape for transit delay, and seeded so it's reproducible.
