# BLUM roadmap

Priorities after the [2.3.0 release](https://github.com/SignalLayerLabs/Blum/releases/tag/v2.3.0). This is a direction of work, not a delivery-date or performance promise.

## Available foundation

The current product exposes five research workspaces, prospective call registration, separate equity/ETF and Forex evaluation, paper execution, bounded ASCENT experiments and one-way verified GitHub deployment. See the [project presentation](.github/README.md), [changelog](CHANGELOG.md) and [current evidence policy](docs/research/data-quality.md) for their scope and limitations.

## Next priorities

| Priority | What should improve | Evidence needed before claiming success |
| --- | --- | --- |
| **Prospective outcome quality** | Mature calls with complete fill, cost and benchmark contracts | Qualified observations, closure-date/asset coverage and explicit exclusions reported separately for each market |
| **Durable research history** | Stronger recovery and continuity for registrations and experiments | Verified external PostgreSQL durability/recovery configuration and rehearsed restore checks; periodic embedded backups alone do not establish zero-loss recovery |
| **Replacement training evidence** | Causal, licensed, deduplicated inputs with observable cutoffs | A reviewed source audit, immutable split/lineage manifests and holdout eligibility before enabling paid training or new promotion |
| **Research validation** | Better regime coverage, concentration controls and uncertainty reporting | Independent samples, cost sensitivity, frozen evaluation and documented statistical limits |
| **Product clarity** | Easier explanation of qualification, stale data and research blockers | Reproducible UX findings, accurate view contracts and accessible real-state interfaces |
| **Maintainability** | Smaller module boundaries where existing broad services are difficult to change | A scoped import/API migration with compatibility checks, rather than renaming files for appearance |

## How work enters the roadmap

Open an [evidence-based proposal](https://github.com/SignalLayerLabs/Blum/issues/new?template=feature_request.yml) with a concrete problem, affected component, validation plan and known tradeoffs. Financial behavior changes require point-in-time reasoning, realistic accounting and an explicit evidence threshold.

BLUM does not schedule broker execution, promise returns or treat competitor superiority as a verified milestone. Future model work remains subject to the source quarantine and explicit operational authorization.

The [previous long-form roadmap](docs/archive/roadmap-pre-2.3.md) is preserved for historical context. It contains earlier plans and descriptions that are superseded by current release documentation.
