from app.services.bootstrap import price_row_from_cache


def test_inconsistent_ohlc_and_nonfinite_prices_are_rejected():
    row = {'date':'2023-06-05', 'open':'181.26', 'high':'180.8199',
           'low':'178.44', 'close':'179.58', 'volume':'34465800', 'provider':'nasdaq_api'}
    assert price_row_from_cache(1, row) is None
    assert price_row_from_cache(1, {**row, 'open':'179', 'close':'nan'}) is None
    assert price_row_from_cache(1, {**row, 'open':'179', 'volume':'-1'}) is None


def test_missing_volume_is_preserved_as_missing():
    row = {'date':'2023-06-05', 'open':'179', 'high':'180.8199',
           'low':'178.44', 'close':'179.58', 'volume':'', 'provider':'nasdaq_api'}
    accepted = price_row_from_cache(1, row)
    assert accepted['volume'] is None
    assert accepted['provider'] == 'nasdaq_api'


def test_persisted_bad_bars_are_excluded_from_replay_without_filling_missing_volume():
    from datetime import date
    import pandas as pd
    from app.models import PriceHistory
    from app.services.learning_loop import price_frame
    rows = [PriceHistory(asset_id=1,date=date(2023,6,5),open=181.26,high=180.8199,low=178.44,close=179.58),
            PriceHistory(asset_id=1,date=date(2023,6,6),open=179,high=181,low=178,close=180,volume=None)]
    frame = price_frame(rows)
    assert len(frame) == 1
    assert frame.iloc[0]['date'] == date(2023,6,6)
    assert pd.isna(frame.iloc[0]['volume'])
