#!/usr/bin/env python3
"""Exercise the real durable worker on local, hashed market sources in a fresh DB.

No network requests, production writes, promotion, or raw-price redistribution.
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path
import tempfile
import time

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models import Asset, PriceHistory, ReplayMarketBar
from app.services.curriculum_worker import TradingCurriculumWorker, SOURCE_POLICY


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--equity-cache",
        type=Path,
        default=Path("backend/app/data/historical_prices_seed.csv.gz"),
    )
    parser.add_argument(
        "--forex",
        action="append",
        default=[],
        help="SYMBOL=/path/to/raw-yahoo-chart.json",
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    now = datetime(2026, 10, 19, 12)
    started = time.monotonic()
    sources = []
    with tempfile.TemporaryDirectory(prefix="blum-source-recovery-") as directory:
        engine = create_engine("sqlite:///" + str(Path(directory) / "validation.db"))
        Base.metadata.create_all(engine)
        with Session(engine) as db:
            assets = {}

            def asset(symbol, market):
                key = (symbol, market)
                if key not in assets:
                    row = Asset(
                        ticker=symbol,
                        name=symbol,
                        country=market,
                        category="ETF" if market == "USA" else "Forex",
                        asset_type="ETF" if market == "USA" else "Forex",
                        sector="Research",
                        currency="USD",
                        exchange="Research",
                        is_active=True,
                    )
                    db.add(row)
                    db.flush()
                    assets[key] = row
                return assets[key]

            with gzip.open(args.equity_cache, "rt") as stream:
                for row in csv.DictReader(stream):
                    if row["ticker"] not in ("SPY", "QQQ"):
                        continue
                    a = asset(row["ticker"], "USA")
                    values = {
                        k: float(row[k]) if row.get(k) else None
                        for k in ("open", "high", "low", "close", "volume")
                    }
                    db.add(
                        PriceHistory(
                            asset_id=a.id,
                            date=datetime.fromisoformat(row["date"]).date(),
                            provider=row.get("provider", "cache"),
                            **values,
                        )
                    )
            sources.append(
                dict(
                    kind="repository_daily_cache",
                    sha256=hashlib.sha256(args.equity_cache.read_bytes()).hexdigest(),
                )
            )
            for specification in args.forex:
                symbol, path = specification.rsplit("=", 1)
                path = Path(path)
                result = json.loads(path.read_text())["chart"]["result"][0]
                quotes = result["indicators"]["quote"][0]
                a = asset(symbol, "Forex")
                source_sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
                count = 0
                for i, timestamp in enumerate(result["timestamp"]):
                    if quotes["close"][i] is None:
                        continue  # absent candle stays a gap
                    values = {
                        k: quotes[k][i]
                        for k in ("open", "high", "low", "close", "volume")
                    }
                    db.add(
                        ReplayMarketBar(
                            asset_id=a.id,
                            source_symbol=symbol,
                            normalized_symbol=symbol,
                            market="Forex",
                            timeframe="1d",
                            bar_timestamp=datetime.fromtimestamp(
                                timestamp, timezone.utc
                            ).replace(tzinfo=None),
                            provider="yahoo_chart",
                            acquired_at=now,
                            data_quality_score=95,
                            source_metadata={
                                "source_sha256": source_sha256
                            },
                            **values,
                        )
                    )
                    count += 1
                sources.append(
                    dict(
                        symbol=symbol,
                        kind="raw_yahoo_chart",
                        input_rows=count,
                        sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                    )
                )
            db.commit()
        worker = TradingCurriculumWorker()
        # Each call has the same per-market learner used by the minute job.
        for cycle in range(80):
            with Session(engine) as db:
                result = worker.run_once(db, now=now, max_lanes=2, max_seconds=20)
                if result["status"] != "ok":
                    raise RuntimeError(result)
                snapshot = worker.snapshot(db)
                if snapshot["lanes"] and all(
                    l["training_status"].startswith("PACK_EXHAUSTED")
                    for l in snapshot["lanes"]
                ):
                    break
        else:
            raise RuntimeError("Bounded source recovery did not finish")
        before = {
            l["lane"]: (
                l["source_hash"],
                l["checkpoint"],
                l["training_episodes"],
                l["learned_outcomes"],
            )
            for l in snapshot["lanes"]
        }
        with Session(
            engine
        ) as db:  # new session: database is the only retained checkpoint
            worker.run_once(db, now=now, max_lanes=2, max_seconds=20)
            resumed = worker.snapshot(db)
        after = {
            l["lane"]: (
                l["source_hash"],
                l["checkpoint"],
                l["training_episodes"],
                l["learned_outcomes"],
            )
            for l in resumed["lanes"]
        }
        if before != after:
            raise RuntimeError("Restart duplicated historical learning")
        if {l["market"] for l in resumed["lanes"]} != {"USA", "FOREX"}:
            raise RuntimeError("Missing independent market lane")
        if any(not l["learned_outcomes"] for l in resumed["lanes"]):
            raise RuntimeError("A corpus produced no useful outcomes")
        receipt = dict(
            source_policy=SOURCE_POLICY,
            scope="Isolated durable-worker recovery; not live trading or alpha qualification",
            sources=sources,
            clock=now.isoformat(),
            cycles=cycle + 1,
            seconds=round(time.monotonic() - started, 3),
            restart_duplicate_updates=0,
            confirmation_opened=False,
            lanes=resumed["lanes"],
            limitations=[
                "Dependent expert outcomes, not independent trades or forward alpha.",
                "Source clock cleanup changes the corpus; returns cannot be compared with legacy contaminated partitions.",
                "Current-date cash and corporate actions are not independently audited point-in-time vendor vintages.",
                "No production state was read or written; live learning still requires post-deployment verification.",
            ],
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(receipt, indent=2, allow_nan=False) + "\n")
    print(
        json.dumps(
            dict(
                seconds=receipt["seconds"],
                cycles=receipt["cycles"],
                restart_duplicate_updates=0,
                lanes=[
                    {
                        k: l.get(k)
                        for k in (
                            "lane",
                            "source_rows",
                            "learned_outcomes",
                            "training_episodes",
                            "productive_episodes",
                            "training_status",
                            "source_audit",
                        )
                    }
                    for l in receipt["lanes"]
                ],
            ),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
