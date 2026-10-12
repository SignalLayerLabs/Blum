"""Run or resume one bounded ASCENT cycle using the configured BLUM database."""

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.core.database import SessionLocal
from app.services.ascent.engine import AscentEvolutionEngine


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--market", choices=("equity", "forex"), default="equity")
    parser.add_argument("--lane", choices=("REPLAY_EVIDENCE", "PAPER_FORWARD_FOREX"), default="REPLAY_EVIDENCE")
    parser.add_argument("--resume", help="Existing generation UID; no new hypothesis or holdout")
    parser.add_argument("--status", action="store_true", help="Read stored results without starting research")
    args = parser.parse_args()
    with SessionLocal() as db:
        service = AscentEvolutionEngine()
        result = service.snapshot(db) if args.status else service.run_once(db,
            market_family=args.market, evidence_lane=args.lane, generation_uid=args.resume)
        print(json.dumps(result, indent=2))
    return 1 if result.get("status") == "FAILED" else 0


if __name__ == "__main__":
    raise SystemExit(main())
