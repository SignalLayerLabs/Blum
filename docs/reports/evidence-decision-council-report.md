# BLUM Evidence-Bound Decision Council

> Historical record. This document describes an earlier implementation or audit; its counts, configuration and readiness claims are not the current release status. Start with the [documentation index](../README.md) and [current data policy](../research/data-quality.md).

## External architecture review

The implementation was informed by the public architecture of
[TauricResearch/TradingAgents](https://github.com/TauricResearch/TradingAgents),
reviewed at commit `a33fd4c0f134485a43553a2c23a63cb14adbd88f` (Apache-2.0).
TradingAgents separates market, social, news and fundamental analysts; runs a
bull/bear research debate; runs aggressive, neutral and conservative risk
reviews; and lets a portfolio manager issue the final decision. It also keeps
decision and outcome reflections.

BLUM did not copy the repository or introduce its LangGraph/provider runtime.
BLUM already has broader quantitative evidence, point-in-time memory,
reliability matrices, execution simulation and outcome tracking. The useful
missing capability was a persistent, resumable decision council connecting
those systems.

## Implemented architecture

`EvidenceBoundDecisionCouncil` consumes one stored `BlumKnowledgeRecord` and
its point-in-time `EngineVote` rows. It persists four ordered stages:

1. independent analyst turns;
2. bull/bear debate plus research manager synthesis;
3. aggressive, conservative and neutral risk review;
4. portfolio manager verdict.

The council is deterministic and never fetches market data or invokes an LLM.
Every turn cites persisted evidence. Missing invalidation, missing reward/risk,
weak evidence, insufficient independent sources or high disagreement force a
`WAIT` verdict. A background reflection pass compares mature outcomes with the
benchmark and records whether direction and actionability helped. Only a
minimum sample of same-ticker reflections can adjust later confidence.

## Runtime

- `DecisionCouncilWorker` prioritizes the newest unprocessed records that have
  at least two independent engine votes, in bounded slices with a persistent
  cursor.
- The worker is isolated in the `decision_council` queue and runs every ten
  minutes by default.
- `decision_council_summary` is generated asynchronously and read by GET.
- `GET /api/engine/decision-council` returns only the latest snapshot.
- `GET /api/engine/decision-council/runs/{run_id}` returns an auditable bounded
  replay of stored turns and reflections.

## Safety

- no future knowledge may enter a decision clock;
- outcomes already known before the council clock are ineligible for reflection
  or memory adjustment;
- no hidden model-weight change occurs;
- no source-code self-modification occurs;
- no action is emitted without stored risk controls;
- disagreement lowers confidence;
- prior outcomes cannot affect confidence before the configured sample gate;
- no result is represented as proof of alpha or guaranteed profit.

## Known limitations

The council can only be as good as the persisted engine votes and risk plan.
It does not create missing fundamental, sentiment or market evidence. Its
reflection memory currently starts with same-ticker outcomes; broader
sector/regime transfer must remain gated by independent validation. A completed
council verdict is research evidence and does not bypass BLUM execution or
portfolio risk authority.
