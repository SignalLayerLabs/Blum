"""Offline price-only ASCENT reproducibility check; no production or forward authority."""

import argparse
from uuid import uuid4
from pathlib import Path
import sys, hashlib, json
from datetime import datetime, time
import pandas as pd
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

repo = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output-dir', type=Path, help='New local verification workspace; existing database paths are rejected.')
args = parser.parse_args()
sys.path.insert(0, str(repo / 'backend'))
from app.core.database import Base
from app.models import AscentExperiment
from app.services.technical_analysis_engine import TechnicalAnalysisEngine
from app.services.learning_loop import PredictionEngine, OutcomeEvaluator, infer_market_regime, infer_volatility_regime, data_quality_score
from app.services.trading_ml.contracts import TradingMLExample
from app.services.ascent.engine import AscentEvolutionEngine

cache = repo / 'backend/app/data/historical_prices_seed.csv.gz'
cache_sha256 = hashlib.sha256(cache.read_bytes()).hexdigest()
prices = pd.read_csv(cache)
prices['date'] = pd.to_datetime(prices['date'])
benchmark = prices[prices.ticker == 'SPY'].set_index('date')['close']
analyzer, predictor, evaluator = TechnicalAnalysisEngine(), PredictionEngine(), OutcomeEvaluator()
examples = []
for ticker in ('SPY','QQQ','IWM','SMH','XLF','XLE'):
    frame = prices[prices.ticker == ticker].sort_values('date').reset_index(drop=True)
    for index in range(520, len(frame) - 30, 5):
        past, future = frame.iloc[:index+1].copy(), frame.iloc[index+1:].copy()
        analysis_date = past.iloc[-1]['date'].date()
        technical = analyzer.analyze(past, timeframe='1Y')
        bench_past = prices[(prices.ticker == 'SPY') & (prices.date <= pd.Timestamp(analysis_date))]
        market = {'benchmark':'SPY','market_regime':infer_market_regime(bench_past),
                  'volatility_regime':infer_volatility_regime(bench_past),'risk_sentiment':'balanced'}
        market['risk_sentiment'] = 'risk_on' if market['market_regime'] in ('Bull Expansion','Recovery','Rotation') else 'risk_off' if market['market_regime'] in ('Risk-Off','Panic') else 'balanced'
        news, fundamentals, macro = {'article_count_total_as_of':0}, {'status':'missing'}, {'status':'missing'}
        context = {'asset':{'ticker':ticker,'asset_type':'ETF','country':'USA','sector':'ETF'},
            'analysis_date':analysis_date.isoformat(),'initial_price':float(past.iloc[-1]['close']),
            'past_prices':past,'technical':technical,'news':news,'fundamentals':fundamentals,'macro':macro,
            'market_context':market,'data_quality_score':data_quality_score(past,news,fundamentals,macro),
            'point_in_time_policy':{'prices':'Closed historical bars only; labels supplied separately.'}}
        forecast = predictor.predict(context, db=None)
        label_context = {**context, 'future_prices':future}
        outcome = evaluator.evaluate(label_context, 'short', forecast['timeframes']['short'])
        realized = outcome.get('realized_net_r')
        if realized is None: continue
        coverage = float(past.tail(252)[['open','high','low','close','volume']].notna().to_numpy().mean()) * 100
        terminal = outcome['evaluation_date']
        risk_percent = abs(float(forecast['timeframes']['short']['invalidation_level']) - context['initial_price']) / context['initial_price'] * 100
        benchmark_return = (float(benchmark.loc[pd.Timestamp(terminal)]) / float(benchmark.loc[pd.Timestamp(analysis_date)]) - 1) * 100
        examples.append(TradingMLExample(source_object_type='verified_cache_baseline',source_object_id=f'{ticker}:{analysis_date}',
            market_family='equity',evidence_lane='REPLAY_EVIDENCE',decision_timestamp=datetime.combine(analysis_date,time.max),
            outcome_timestamp=datetime.combine(terminal,time.max),asset_key=ticker,setup_type='existing_baseline_forecast',
            regime=market['market_regime'],features={'confidence':forecast['prediction']['aggregate_confidence'],
                'data_quality_score':coverage,'expected_cost':outcome['modeled_cost_r'],
                'quality_scope':'OHLCV completeness; no fundamental or news-quality claim',
                'provider':str(past.iloc[-1]['provider']), 'data_revision':cache_sha256, 'forecast_model_version':'base-static'},realized_net_r=float(realized),label_positive_r=int(realized>0),
            benchmark_excess=float(realized)-benchmark_return/risk_percent,sample_weight=1.0))
    print(f'{ticker}: accumulated {len(examples)} genuine baseline forecasts',flush=True)
root = args.output_dir or repo / '.artifacts/ascent-verification' / uuid4().hex
root.mkdir(parents=True, exist_ok=True)
if (root / 'validation.db').exists():
    raise SystemExit('Use a new verification workspace; existing research databases are never overwritten.')
db_engine = create_engine(f'sqlite:///{root / "validation.db"}')
Base.metadata.create_all(db_engine)
with Session(db_engine) as db:
    service = AscentEvolutionEngine(artifact_root=root / 'candidates',enabled=True)
    result = service.run_once(db,examples=tuple(examples))
    snapshot = service.snapshot(db)
report = {'verification_kind':'REPRODUCIBILITY_CHECK_NOT_PROMOTION_EVIDENCE', 'verification_scope':'Price-only historical calibration research using existing BLUM deterministic forecasts and cost model. Not forward evidence or a production promotion.',
    'cache_sha256':hashlib.sha256(cache.read_bytes()).hexdigest(),'price_rows':len(prices),
    'forecast_rows':len(examples),'quality_metric':'Observed OHLCV completeness; existing broader context-quality score is not overridden.',
    'benchmark':'Same-period SPY return converted to each stored risk unit; not portfolio benchmark returns.',
    'generation':result,'observatory':snapshot}
output = root / 'report.json'
output.write_text(json.dumps(report,indent=2))
print(json.dumps({'status':result['status'],'forecast_rows':len(examples),'blockers':result.get('blockers'),
    'output':str(output)},indent=2),flush=True)
