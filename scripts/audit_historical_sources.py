"""Reproduce packaged source acceptance counts without importing runtime state."""
from __future__ import annotations
import csv
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from app.services.bootstrap import price_row_from_cache
from app.services.trading_ml.forex_history import ForexHistoricalDatasetService, bundled_forex_history_path, KAGGLE_FOREX_SOURCE_URL


def audit() -> dict:
    cache = ROOT / 'backend/app/data/historical_prices_seed.csv.gz'
    accepted = 0
    rejected = []
    missing_volume = 0
    seen = set()
    duplicate_keys = 0
    with gzip.open(cache, 'rt', newline='') as handle:
        for line, row in enumerate(csv.DictReader(handle), 2):
            key = (row['ticker'], row['date'])
            if key in seen:
                duplicate_keys += 1
                rejected.append({'line':line, 'ticker':key[0], 'date':key[1], 'reason':'DUPLICATE_KEY'})
                continue
            seen.add(key)
            value = price_row_from_cache(1, row)
            if value is None:
                rejected.append({'line':line, **row, 'reason':'INVALID_OHLCV'})
                continue
            accepted += 1
            missing_volume += int(value['volume'] is None)
    forex = ForexHistoricalDatasetService(source_path=bundled_forex_history_path(), source_url=KAGGLE_FOREX_SOURCE_URL,
        license_name='CC BY-SA 4.0', source_version='1').prepare()
    return {'policy_version':'historical-quality-v2', 'price_cache_sha256':hashlib.sha256(cache.read_bytes()).hexdigest(),
        'accepted_price_rows':accepted, 'accepted_price_rows_with_missing_volume':missing_volume,
        'duplicate_price_keys':duplicate_keys, 'rejected_price_rows':rejected,
        'forex':forex.provenance, 'use_boundary':'historical replay only; no forward or dividend-inclusive return claim'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='Verify the reviewed source revisions and acceptance counts.')
    args = parser.parse_args()
    result = audit()
    if args.check:
        expected = json.loads((ROOT / 'backend/app/data/history_acceptance_policy.json').read_text())
        actual = {key:result[key] for key in ['price_cache_sha256','accepted_price_rows','accepted_price_rows_with_missing_volume']}
        actual.update(rejected_price_rows=len(result['rejected_price_rows']),
            forex_source_sha256=result['forex']['source_sha256'],
            accepted_forex_snapshots=result['forex']['daily_bars_created'],
            forex_conflicting_rows_quarantined=result['forex']['conflicting_rows_quarantined'],
            forex_weekend_rows_quarantined=result['forex']['weekend_rows_quarantined'],
            forex_causal_examples=result['forex']['examples_created'])
        if any(expected.get(key) != value for key, value in actual.items()):
            raise SystemExit('Historical source revision or acceptance policy drifted; review the data before release.')
    print(json.dumps(result, indent=2, sort_keys=True))
