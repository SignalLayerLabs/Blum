"""Sampling units and portfolio outcomes remain separate from performance claims."""
from math import sqrt
import numpy as np
from scipy.stats import skew, kurtosis, norm


def probabilistic_sharpe(returns, *, reference: float=0.0) -> dict:
    values=np.asarray(returns,dtype=float)
    if values.ndim!=1 or not np.isfinite(values).all() or not np.isfinite(reference):
        raise ValueError('finite_one_dimensional_returns_required')
    empty=dict(per_observation_sharpe=None,annualized_sharpe=None,probability_above_reference=None,
        sample_size=len(values),reference=reference,method='PSR_per_observation_not_deflated')
    if len(values)<4 or values.std(ddof=1)<=0: return empty
    sr=float(values.mean()/values.std(ddof=1))
    variance=1-float(skew(values,bias=False))*sr+(float(kurtosis(values,fisher=False,bias=False))-1)*sr*sr/4
    if not np.isfinite(variance) or variance<=0: return empty
    return empty|dict(per_observation_sharpe=sr,probability_above_reference=float(norm.cdf((sr-reference)*sqrt(len(values)-1)/sqrt(variance))))


def paired_interval(candidate: list[dict], baseline: list[dict], *, trials: int=1, seed: int=17) -> dict:
    unavailable=dict(status='UNAVAILABLE',reason='aligned_complete_paths_and_twenty_sessions_required',lower_percent=None,upper_percent=None)
    if len(candidate)!=len(baseline) or len(candidate)<21: return unavailable
    if [r['at'] for r in candidate]!=[r['at'] for r in baseline] or len({r['at'] for r in candidate})!=len(candidate): return unavailable
    if any(r['nav'] is None for r in candidate+baseline): return unavailable
    c=np.array([float(r['nav']) for r in candidate]);b=np.array([float(r['nav']) for r in baseline])
    if not np.isfinite(c).all() or not np.isfinite(b).all() or np.any(c<=0) or np.any(b<=0): return unavailable
    excess=(c[1:]/c[:-1]-1)-(b[1:]/b[:-1]-1)
    # Cluster same-session observations before resampling contiguous date blocks.
    groups={}
    for row,value in zip(candidate[1:],excess): groups.setdefault(row['at'][:10],[]).append(value)
    values=np.array([sum(v) for v in groups.values()])
    if len(values)<20: return unavailable
    trials=max(1,int(trials));confidence=1-0.05/trials;alpha=(1-confidence)/2
    block=max(2,int(len(values)**(1/3)));count=int(np.ceil(len(values)/block));rng=np.random.default_rng(seed)
    means=[]
    for _ in range(2000):
        starts=rng.integers(0,len(values)-block+1,size=count)
        sample=np.concatenate([values[i:i+block] for i in starts])[:len(values)]
        means.append(float(sample.mean()))
    return dict(status='AVAILABLE',mean_period_excess_percent=float(values.mean()*100),lower_percent=float(np.quantile(means,alpha)*100),
        upper_percent=float(np.quantile(means,1-alpha)*100),confidence=confidence,family_trials=trials,sessions=len(values),
        method='session_clustered_contiguous_block_bootstrap_bonferroni',limitations='Assumes local dependence captured by declared blocks; not universal protection against selection bias.')


def score_returns(curve: list[dict]) -> dict:
    if len(curve)<2 or any(row['nav'] is None for row in curve): return dict(status='INCOMPLETE',psr=None)
    values=np.array([float(row['nav']) for row in curve])
    if not np.isfinite(values).all() or np.any(values<=0): return dict(status='INCOMPLETE',psr=None)
    returns=values[1:]/values[:-1]-1
    return dict(status='AVAILABLE',psr=probabilistic_sharpe(returns),
        dsr=dict(status='UNAVAILABLE',reason='Independent trial-Sharpe distribution not established.'),
        pbo=dict(status='UNAVAILABLE',reason='Family-wide symmetric in/out-of-sample ranking matrix not established.'))
