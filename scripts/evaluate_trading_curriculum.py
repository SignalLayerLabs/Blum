#!/usr/bin/env python3
"""Reproduce bounded research checkpoints without touching a runtime database."""

from __future__ import annotations

import argparse
from collections import defaultdict
import csv
from datetime import datetime
import gzip
import hashlib
import json
from pathlib import Path
from zoneinfo import ZoneInfo
from datetime import timedelta, timezone
import time

from app.services import trading_curriculum as k


def evaluate(symbol, market, rows, source):
    accepted, rejected = [], 0
    for row in rows:
        start = datetime.fromisoformat(row.get("start", row["date"]))
        bar = dict(
            start=k.session_start(start, "1d", market).isoformat(),
            available=row.get("available")
            or k.available_at(start, "1d", market).isoformat(),
            **{
                key: float(row[key] or 0)
                for key in ("open", "high", "low", "close", "volume")
            },
        )
        if (
            datetime.fromisoformat(row["date"]).weekday() < 5
            and k.valid_bar(bar)
            and datetime.fromisoformat(bar["available"]) <= datetime.utcnow()
        ):
            accepted.append(bar)
        else:
            rejected += 1
    accepted.sort(key=lambda b: b["start"])
    if len(accepted) < 600 or len({b["start"] for b in accepted}) != len(accepted):
        return dict(
            symbol=symbol,
            market=market,
            status="BLOCKED_SOURCE_QUALITY",
            accepted_rows=len(accepted),
            rejected_rows=rejected,
        )
    split = k.partition(len(accepted))
    kwargs = dict(
        market=market,
        timeframe="1d",
        start=split["development_start"],
        end=split["development_end"],
    )
    model = k.Selector({})
    checkpoints = []
    learned = 0
    for number, window in enumerate(
        [(None, None)] + k.training_windows(len(accepted), seed=17), start=0
    ):
        if number:
            for spec in k.catalogue("1d", market):
                report = k.simulate(
                    accepted,
                    market=market,
                    timeframe="1d",
                    start=window[0],
                    end=window[1],
                    expert=spec,
                )
                for trade in report["trades"]:
                    if trade["status"] == "CLOSED":
                        model.learn(spec.fingerprint, trade["context"], trade["net_r"])
                        learned += 1
        report = k.simulate(accepted, model=model, **kwargs)
        report.pop("trades")
        checkpoints.append(
            dict(
                training_episodes=number,
                learned_dependent_outcomes=learned,
                model_hash=k.digest(model.payload()),
                metrics=report,
            )
        )
    fixed = k.simulate(accepted, expert=k.catalogue("1d", market)[0], **kwargs)
    fixed.pop("trades")
    return dict(
        symbol=symbol,
        market=market,
        status="RESEARCH_ONLY",
        source=source,
        source_pack_hash=k.digest(accepted),
        accepted_rows=len(accepted),
        rejected_rows=rejected,
        train_end=accepted[split["train_end"] - 1]["available"],
        development_start=accepted[split["development_start"]]["available"],
        development_end=accepted[split["development_end"] - 1]["available"],
        window_hash=k.digest(
            accepted[split["development_start"] : split["development_end"]]
        ),
        confirmation_opened=False,
        checkpoints=checkpoints,
        fixed_expert=fixed,
        cash_net_return=0.0,
        initial_to_final_return_change=(
            checkpoints[-1]["metrics"]["net_return"]
            - checkpoints[0]["metrics"]["net_return"]
            if checkpoints[-1]["metrics"]["net_return"] is not None
            and checkpoints[0]["metrics"]["net_return"] is not None
            else None
        ),
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--equity-cache",
        type=Path,
        default=Path("backend/app/data/historical_prices_seed.csv.gz"),
    )
    parser.add_argument(
        "--forex",
        action="append",
        default=[],
        help="SYMBOL=/path/to/daily-OHLC.csv; raw data remains outside Git",
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    started = time.monotonic()
    groups = defaultdict(list)
    with gzip.open(args.equity_cache, "rt") as stream:
        for row in csv.DictReader(stream):
            if row["ticker"] in ("SPY", "QQQ", "IWM", "DIA"):
                groups[row["ticker"]].append(row)
    source = dict(
        path=str(args.equity_cache),
        sha256=hashlib.sha256(args.equity_cache.read_bytes()).hexdigest(),
        provider="repository Nasdaq/Stooq historical cache; mixed provider provenance",
    )
    lanes = [
        evaluate(symbol, "USA", rows, source) for symbol, rows in sorted(groups.items())
    ]
    for spec in args.forex:
        symbol, path = spec.rsplit("=", 1)
        path = Path(path)
        if path.suffix == ".json":
            result = json.loads(path.read_text())["chart"]["result"][0]
            zone = ZoneInfo(result["meta"]["exchangeTimezoneName"])
            quote = result["indicators"]["quote"][0]
            rows = []
            for i, timestamp in enumerate(result["timestamp"]):
                if any(
                    quote[key][i] is None for key in ("open", "high", "low", "close")
                ):
                    continue
                local = datetime.fromtimestamp(timestamp, timezone.utc).astimezone(zone)
                close = (local + timedelta(days=1)).astimezone(timezone.utc).replace(
                    tzinfo=None
                ) + timedelta(minutes=1)
                rows.append(
                    dict(
                        date=local.date().isoformat(),
                        start=datetime.fromtimestamp(timestamp, timezone.utc)
                        .replace(tzinfo=None)
                        .isoformat(),
                        available=close.isoformat(),
                        **{
                            key: quote[key][i] or 0
                            for key in ("open", "high", "low", "close", "volume")
                        },
                    )
                )
        else:
            with path.open() as stream:
                rows = [
                    dict(
                        date=r["Date"],
                        open=r["Open"],
                        high=r["High"],
                        low=r["Low"],
                        close=r["Close"],
                        volume=r.get("Volume", 0),
                    )
                    for r in csv.DictReader(stream)
                ]
        lanes.append(
            evaluate(
                symbol,
                "FOREX",
                rows,
                dict(
                    provider="Yahoo Chart daily, research capacity scenario; provider exchange timezone determines daily opening/closing, one-minute publication lag",
                    sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                ),
            )
        )
    receipt = dict(
        version=k.VERSION,
        cost_version=k.COST_VERSION,
        created_at=datetime.utcnow().isoformat(),
        elapsed_seconds=time.monotonic() - started,
        lanes=lanes,
        forex_status=(
            "EVALUATED_RESEARCH_SCENARIO"
            if args.forex
            else "NOT_EVALUATED_NO_APPROVED_LOCAL_OHLC_PACK"
        ),
        limitations=[
            "Development is reused across checkpoints and is not an independent final test.",
            "Confirmation stays unopened. No promotion or forward alpha claim.",
            "Long-only adaptations; quote-currency cash per lane; no consolidated capital or borrow assumptions.",
            "OHLC fills, spread and capacity are modeled; corporate actions, survivorship and dividends are not fully audited.",
        ],
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(receipt, indent=2, allow_nan=False) + "\n")
    print(
        json.dumps(
            dict(
                output=str(args.output),
                elapsed_seconds=receipt["elapsed_seconds"],
                lanes=[
                    dict(
                        symbol=x["symbol"],
                        status=x["status"],
                        return_change=x.get("initial_to_final_return_change"),
                    )
                    for x in lanes
                ],
            )
        )
    )


if __name__ == "__main__":
    main()
