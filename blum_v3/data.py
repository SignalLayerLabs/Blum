"""Source acceptance preserves rejected rows as counts/reasons, never repairs prices."""
from __future__ import annotations

from collections import defaultdict
from datetime import timedelta
from typing import Iterable

from pydantic import ValidationError

from .domain import AcceptedDataset, Bar, Instrument, Provenance, Rejection, identity


def accept_dataset(instrument: Instrument, rows: Iterable[dict], provenance: Provenance) -> AcceptedDataset:
    groups: dict = defaultdict(list)
    rejected: list[Rejection] = []
    warnings = {'Calendar checked for weekends only; exchange holidays and corporate actions are not certified.'}
    raw_rows = list(rows)
    if len(raw_rows) > 250_000:
        raise ValueError('dataset_row_limit_exceeded')
    for index, raw in enumerate(raw_rows):
        try:
            bar = Bar.model_validate(raw)
            if bar.timestamp.weekday() >= 5:
                raise ValueError('unsupported_weekend_session')
            if bar.available_at > provenance.first_seen_at:
                raise ValueError('availability_after_source_observation')
            groups[bar.timestamp].append((index, bar))
        except (ValidationError, ValueError, TypeError):
            rejected.append(Rejection(row=index, reason='invalid_bar'))
    accepted: list[Bar] = []
    duplicates = 0
    for timestamp in sorted(groups):
        group = groups[timestamp]
        if len({identity(bar) for _, bar in group}) > 1:
            rejected.extend(Rejection(row=index, reason='conflicting_key') for index, _ in group)
            continue
        bar = group[0][1]
        accepted.append(bar)
        duplicates += len(group) - 1
        if bar.volume is None:
            warnings.add('Volume is missing; participation-based equity execution is unavailable on affected bars.')
    if any(b.timestamp - a.available_at > timedelta(days=4) for a, b in zip(accepted, accepted[1:])):
        warnings.add('Source gaps exceed four days; warmup/label continuity must be checked per experiment.')
    contents = dict(instrument=instrument, provenance=provenance, bars=accepted,
                    rejected=sorted(rejected, key=lambda r: r.row), duplicate_count=duplicates)
    return AcceptedDataset(dataset_id=identity(contents), **contents, warnings=tuple(sorted(warnings)))
