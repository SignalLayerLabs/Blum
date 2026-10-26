from datetime import datetime, timezone, timedelta
from decimal import Decimal

import pytest


def observation(**changes):
    row = dict(timestamp='2024-01-02T14:30:00Z', available_at='2024-01-02T21:00:00Z',
               open='100', high='103', low='99', close='102', volume='1000')
    return row | changes


def instrument(**changes):
    from blum_v3.domain import Instrument
    return Instrument(symbol='SPY', market='equity', quote_currency='USD', **changes)


def provenance():
    from blum_v3.domain import Provenance
    return Provenance(provider='contract-fixture', rights='unit testing only',
                      first_seen_at='2024-02-01T00:00:00Z', availability_policy='historical_bar_close')


def test_acceptance_rejects_invalid_rows_and_conflicting_groups():
    from blum_v3.data import accept_dataset
    result = accept_dataset(instrument(), [observation(), observation(), observation(timestamp='2024-01-03T14:30:00Z',available_at='2024-01-03T21:00:00Z'),
        observation(timestamp='2024-01-03T14:30:00Z',available_at='2024-01-03T21:00:00Z',close='101'),
        observation(timestamp='2024-01-04T14:30:00Z',available_at='2024-01-04T21:00:00Z',high='98')], provenance())
    assert len(result.bars) == 1
    assert result.duplicate_count == 1
    assert sorted(item.reason for item in result.rejected) == ['conflicting_key', 'conflicting_key', 'invalid_bar']


@pytest.mark.parametrize('change', [dict(open='NaN'), dict(volume='-1'),dict(timestamp='2024-01-02T14:30:00'),
    dict(available_at='2024-01-02T13:00:00Z'),dict(bid='103',ask='102'),dict(timestamp='2024-01-06T14:30:00Z',available_at='2024-01-06T21:00:00Z')])
def test_bad_observations_are_explicitly_rejected(change):
    from blum_v3.data import accept_dataset
    assert len(accept_dataset(instrument(), [observation(**change)], provenance()).bars) == 0


def test_zero_and_unknown_volume_are_distinct_and_identity_is_stable():
    from blum_v3.data import accept_dataset
    a = accept_dataset(instrument(), [observation(volume=None)], provenance())
    b = accept_dataset(instrument(), [observation(volume='0')], provenance())
    assert a.bars[0].volume is None
    assert b.bars[0].volume == Decimal('0')
    assert a.dataset_id != b.dataset_id
    assert a.dataset_id == accept_dataset(instrument(), [observation(volume=None)], provenance()).dataset_id


def test_dataset_roundtrip_survives_reopen_and_has_immutable_identity(tmp_path):
    from blum_v3.data import accept_dataset
    from blum_v3.storage import Repository
    url = 'sqlite:///' + str(tmp_path/'research.db')
    result = accept_dataset(instrument(), [observation()], provenance())
    db = Repository(url)
    db.save_dataset(result)
    db.save_dataset(result)
    recovered = Repository(url).dataset(result.dataset_id)
    assert recovered.bars[0].close == Decimal('102')
    assert recovered.instrument.symbol == 'SPY'
    assert len(db.list_datasets()) == 1


def test_quotes_require_joint_bid_ask_and_no_future_knowledge():
    from blum_v3.data import accept_dataset
    partial = accept_dataset(instrument(), [observation(bid='100')], provenance())
    assert not partial.bars
    future = accept_dataset(instrument(), [observation(available_at='2024-02-04T21:00:00Z')], provenance())
    assert not future.bars
