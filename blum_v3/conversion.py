"""Observable mid-rate conversion for declared paper scenarios, never broker FX fills."""
from .domain import decimal
from .orders import conversion_rate


def resolve_conversion(repository,instrument,currency,as_of,*,preferred=None):
    if instrument.quote_currency==currency:return None
    candidates=[]
    for item in repository.list_datasets():
        if item['instrument']['market']!='forex':continue
        if preferred and item['dataset_id']!=preferred:continue
        source=repository.dataset(item['dataset_id']);pair=source.instrument
        direct=pair.base_currency==instrument.quote_currency and pair.quote_currency==currency
        inverse=pair.base_currency==currency and pair.quote_currency==instrument.quote_currency
        if not (direct or inverse):continue
        visible=[bar for bar in source.bars if bar.available_at<=as_of]
        if not visible:continue
        bar=visible[-1]
        rate=bar.close if direct else 1/bar.close
        quote=dict(rate=str(rate),at=bar.available_at.isoformat(),source_ref=source.dataset_id)
        try:conversion_rate(instrument,currency,quote,as_of)
        except ValueError:continue
        candidates.append((bar.available_at,source.dataset_id,quote))
    if not candidates:raise ValueError('missing_conversion')
    return max(candidates,key=lambda row:(row[0],row[1]))[2]
