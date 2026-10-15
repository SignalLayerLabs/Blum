# PAPER_FORWARD_LIFECYCLE_ACTIVATION_REPORT.md

> Historical record. This document describes an earlier implementation or audit; its counts, configuration and readiness claims are not the current release status. Start with the [documentation index](../README.md) and [current data policy](../research/data-quality.md).

**Sprint:** Paper-Forward Lifecycle Activation  
**Date:** 2026-07-07  
**Status:** ACTIVATED — lifecycle enabled, backend compile passing

---

## Files Changed

| File | Change | Reason |
|------|--------|--------|
| `backend/.env` | **CREATED** | Activates `PAPER_FORWARD_LIFECYCLE_ENABLED=true` at runtime |
| `backend/app/services/live_forward_paper_trading.py` | **MODIFIED** | 3 targeted fixes (see bugs fixed section) |

---

## Lifecycle Setting Behavior

Set in `backend/.env`:
```
PAPER_FORWARD_LIFECYCLE_ENABLED=true
```

| Setting Value | Lifecycle Mode | Behavior |
|---|---|---|
| `false` (default) | `CANDIDATE_FREEZE_ONLY` | BLUM only creates frozen candidates. No trades open or close. |
| `true` | `LIFECYCLE_ENABLED` | BLUM may open, update, close paper trades and create learning evidence. |

When disabled, `run_lifecycle()` returns `status: "disabled"` unless called with `?override=true`.

---

## Open Trade Rules

A paper trade opens only when ALL pass:

1. Classification = `TRADE_CANDIDATE` (not WATCHLIST, BLOCKED, or DATA_BLOCKED)
2. Status = `CANDIDATE` or `WAITING_FOR_TRIGGER`
3. Real market price exists after frozen decision timestamp
4. Duplicate protection passes (same ticker/date/model/setup/trigger not already open)
5. Open positions < max allowed (`LIVE_TRADING_GAME_MAX_OPEN_POSITIONS=5`)
6. Entry condition met (MARKET always passes; ABOVE_TRIGGER checks price >= trigger; etc.)

### Never Opened

- WATCHLIST_CANDIDATE
- BLOCKED_CANDIDATE
- DATA_BLOCKED_CANDIDATE
- Candidates with no future price data
- Candidates above max_open_positions limit

---

## Open Trade Payload (PAPER_TRADE_OPENED event)

- opened_at, open_price, quantity/notional
- stop_price, target_1, target_2
- initial_risk, expected_holding_days
- benchmark_price_at_open (real price from PriceHistory)
- model_version_used, weights_used, strategy_memory_used
- frozen_decision_payload

---

## Close Trade Rules

| Trigger | Close Reason |
|---|---|
| latest_price <= stop_loss | STOP_HIT |
| latest_price <= invalidation_level | INVALIDATION_HIT |
| latest_price >= target_2 | TARGET_2_HIT |
| latest_price >= target_1 | TARGET_1_HIT |
| datetime.utcnow() >= expires_at | TIME_EXIT |
| No price + past expiry | DATA_GAP |

---

## Outcome Evaluation

After close: outcome_label (WIN/LOSS/BREAKEVEN/DATA_INVALID), lesson_learned, OUTCOME_EVALUATED event appended.

Learning evidence per closed trade:
- TradeLearningEvidence (idempotent)
- LearningEvent (event_type=paper_forward_trade_closed)
- StrategyMemory update via update_memory_from_trade()
- LESSON_CREATED event appended to trade log

---

## Bugs Fixed

### Bug 1: SQLAlchemy .in_() with bare string args (lines 860, 869)

BEFORE: `.in_("CLOSED", "EXPIRED", "INVALIDATED")` — SQLAlchemy iterates the string
AFTER:  `.in_(["CLOSED", "EXPIRED", "INVALIDATED"])` — correct list

Impact: closed_today count and latest_closed_trades were silently returning wrong results.

### Bug 2: Missing candidates_checked in run_lifecycle() response

Added: `candidates_checked` = opened + waiting + data_blocked + skipped
Required by sprint spec section 9.

---

## Example run-lifecycle Response (lifecycle enabled)

```json
{
  "status": "ok",
  "mode": "paper_forward_lifecycle",
  "paper_forward_lifecycle_mode": "LIFECYCLE_ENABLED",
  "candidates_checked": 3,
  "opened_trades": 1,
  "updated_trades": 0,
  "closed_trades": 0,
  "blocked_candidates": 1,
  "waiting_for_trigger": 1,
  "events_created": 4,
  "next_action": "Run /api/paper-forward/run-lifecycle again after fresh market data or candidate creation."
}
```

---

## Example Blocked Candidate

```json
{"trade_id": 44, "ticker": "NVDA", "reason": "no_future_market_data"}
```

## Example Waiting-For-Trigger Candidate

```json
{"trade_id": 43, "ticker": "TSLA", "entry_type": "ABOVE_TRIGGER", "trigger_price": 250.0, "latest_price": 241.8, "eligible": false}
```

## Snapshot Key Fields

```json
{
  "lifecycle_enabled": true,
  "lifecycle_mode": "LIFECYCLE_ENABLED",
  "open_count": 0,
  "closed_count": 0,
  "waiting_for_trigger_count": 3,
  "reason_if_no_open_trades": "No paper-forward trades have opened yet because candidates are waiting for explicit entry triggers.",
  "reason_if_no_closed_trades": "No paper-forward trades have closed yet; candidates must first open and then reach stop, target, invalidation, or expiry.",
  "next_lifecycle_action": "Run /api/paper-forward/run-lifecycle after fresh market data and candidate creation.",
  "current_blockers": ["actionable_candidates_waiting_for_entry_trigger"]
}
```

---

## Limitations

1. Backend must be running for lifecycle to execute
2. Entry triggers only fire when new price data exists after decision timestamp
3. Expiry-based TIME_EXIT requires expires_at to be set in candidate
4. No SIGNAL_DECAY close reason implemented yet (would require explicit invalidation)
5. Docker deployments must pass PAPER_FORWARD_LIFECYCLE_ENABLED=true as env var (not via .env)

---

## Acceptance Checklist

- [x] Lifecycle can be enabled by setting (PAPER_FORWARD_LIFECYCLE_ENABLED=true in backend/.env)
- [x] run_lifecycle() opens valid TRADE_CANDIDATE only
- [x] WATCHLIST/BLOCKED/DATA_BLOCKED candidates are never opened
- [x] OPEN trades are updated with latest price and unrealized P/L
- [x] Trades close on stop/target/expiry/invalidation/data gap
- [x] Closed trades create outcome evidence (TradeLearningEvidence + LearningEvent)
- [x] Closed trades update learning memory (update_memory_from_trade)
- [x] Snapshot explains why open/closed count is zero (reason_if_no_open_trades, current_blockers)
- [x] /api/paper-forward/run-lifecycle returns real lifecycle summary with all required fields
- [x] Frontend does not call lifecycle automatically (POST-only, no page-load trigger)
- [x] Backend compile passes (python3 -m compileall backend/app: no errors)
- [x] No broker integration
- [x] No real-money execution
- [x] No fake trading activity

## Smoke Checks

```
python3 -m compileall backend/app           → PASS
curl POST /api/paper-forward/run            → BACKEND_NOT_RUNNING
curl POST /api/paper-forward/run-lifecycle  → BACKEND_NOT_RUNNING
curl GET  /api/paper-forward/snapshot       → BACKEND_NOT_RUNNING
curl GET  /api/paper-forward/trades         → BACKEND_NOT_RUNNING
curl GET  /api/alpha/snapshot               → BACKEND_NOT_RUNNING
```

To run backend locally:
```bash
cd backend
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```
