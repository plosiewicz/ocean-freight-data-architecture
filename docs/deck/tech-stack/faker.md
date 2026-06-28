# Faker

**Layer:** synthetic identifiers and labels for the generated event layer.

## What it does
Faker generates realistic-looking fake identifiers/text — names, references, addresses. Seeded via
`Faker.seed(N)` for deterministic output.

## Role in our project
- `data_gen/`: synthetic carrier names, booking references, and similar labels on the synthetic
  bookings/container-events that a real public feed doesn't provide.
- Seeded so the labels are reproducible alongside the NumPy draws — same `synthetic.sha256` contract.
- **Pinned to an exact patch version**, because Faker explicitly does *not* guarantee output stability
  across patch releases — an unpinned bump would silently break byte-reproducibility.

## Why it's the best option here
- **It's the standard, batteries-included fake-data library** — covers the identifier/label surface we
  need without hand-rolling generators.
- **Deterministic when seeded**, which is mandatory for our "reproduce the demo byte-for-byte" goal.
- Cheap, pure-Python, no service dependency.

## Alternatives considered
| Alternative | Why not here | When you'd pick it |
|---|---|---|
| Hand-rolled string generators | Reinventing Faker; more code, more bugs, no benefit | Hyper-specific formats Faker can't produce |
| Mimesis | Comparable library; Faker is the more common default and sufficient | If you specifically need Mimesis' speed/locales |
| SDV / Gretel | Statistical synthesizers for *values/distributions*, not labels; overkill for identifiers | Learning real joint distributions (see [`numpy.md`](numpy.md)) |

## Likely Q&A
- *"Why pin Faker exactly?"* — Faker doesn't guarantee output stability across patch versions; pinning
  the patch keeps the synthetic identifiers byte-stable so the demo and `synthetic.sha256` reproduce.
- *"What's real vs. faked?"* — ships/ports/codes are real; carrier *names* and booking *references* on
  the synthetic event layer are Faker-generated and flagged `provenance="synthetic"`.
