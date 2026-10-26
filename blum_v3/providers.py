"""Fixed-host, opt-in public historical data. Provider failure never fabricates bars."""
from datetime import datetime,timedelta,timezone
from urllib.parse import quote
import httpx

from .domain import Instrument,Provenance,now
from .data import accept_dataset


def fetch_history(symbol: str,market: str,*,range_days=365):
    if not 30<=range_days<=3650: raise ValueError('history_range_must_be_30_to_3650_days')
    normalized=symbol.upper().strip()
    is_fx=market=='forex'
    pair=normalized.removesuffix('=X')
    instrument=Instrument(symbol=pair if is_fx else normalized,market=market,
        quote_currency=pair[3:] if is_fx else 'USD',base_currency=pair[:3] if is_fx else None,
        tick_size='0.00001' if is_fx and not pair.endswith('JPY') else ('0.001' if is_fx else '0.01'))
    if is_fx and (len(pair)!=6 or not pair.isalpha()): raise ValueError('six_letter_fx_pair_required')
    ticker=pair+'=X' if is_fx else normalized
    observed=now();start=observed-timedelta(days=range_days)
    try:
        response=httpx.get('https://query1.finance.yahoo.com/v8/finance/chart/'+quote(ticker,safe=''),
            params=dict(period1=int(start.timestamp()),period2=int(observed.timestamp()),interval='1d',events='history'),
            headers={'User-Agent':'BlumResearch/3.0'},timeout=30,follow_redirects=False)
        response.raise_for_status();payload=response.json()
        result=payload['chart']['result'][0];quotes=result['indicators']['quote'][0]
        if not is_fx and result['meta'].get('currency')!='USD': raise ValueError('history_currency_requires_explicit_instrument')
        rows=[]
        for i,timestamp in enumerate(result.get('timestamp',[])):
            at=datetime.fromtimestamp(timestamp,tz=timezone.utc)
            # Conservative daily availability; historical vendor timestamps are not certified first-seen clocks.
            available=at+timedelta(hours=24 if is_fx else 6,minutes=0 if is_fx else 30)
            if available>observed: continue
            values={key:quotes.get(key,[])[i] for key in ['open','high','low','close','volume']}
            if any(values[k] is None for k in ['open','high','low','close']): continue
            rows.append(dict(timestamp=at,available_at=available,**values))
    except (httpx.HTTPError,KeyError,IndexError,TypeError) as error:
        raise ValueError('history_provider_unavailable_or_invalid_response') from error
    provenance=Provenance(provider='Yahoo public historical chart',rights='Provider terms apply; research use; no redistribution entitlement established.',
        first_seen_at=observed,availability_policy='historical_bar_close',source_url='https://finance.yahoo.com/',
        source_revision=str(int(observed.timestamp())),adjustment_policy='vendor_historical_prices_actions_not_certified')
    return accept_dataset(instrument,rows,provenance)
