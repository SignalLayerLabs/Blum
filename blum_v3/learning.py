"""Small, serializable model challengers trained only on declared earlier examples."""
from datetime import timedelta
import numpy as np

from .domain import utc


def purged_splits(decisions, outcomes, *, folds=3, embargo_days=1):
    if len(decisions)!=len(outcomes) or folds<2 or embargo_days<0: raise ValueError('invalid_split_input')
    times=[utc(v) for v in decisions];ends=[utc(v) for v in outcomes]
    if any(a>=b for a,b in zip(times,times[1:])) or any(e<d for d,e in zip(times,ends)): raise ValueError('nonchronological_examples')
    blocks=np.array_split(np.arange(len(times)),folds+1);result=[]
    for valid in blocks[1:]:
        if not len(valid): continue
        cutoff=times[int(valid[0])]-timedelta(days=embargo_days)
        train=np.array([i for i,t in enumerate(times) if t<times[int(valid[0])] and ends[i]<cutoff],dtype=int)
        if len(train): result.append((train,valid))
    return result


def fit_challenger(train_x,train_y,validation_x,*,algorithm='ridge'):
    x=np.asarray(train_x,dtype=float);y=np.asarray(train_y,dtype=float);v=np.asarray(validation_x,dtype=float)
    if x.ndim!=2 or v.ndim!=2 or x.shape[1]!=v.shape[1] or len(y)!=len(x) or len(x)<4 or not all(np.isfinite(a).all() for a in [x,y,v]):
        raise ValueError('invalid_model_examples')
    mean=x.mean(axis=0);scale=x.std(axis=0);scale=np.where(scale>1e-12,scale,1)
    standardized=(x-mean)/scale;target_mean=float(y.mean())
    if algorithm=='ridge':
        beta=np.linalg.solve(standardized.T@standardized+np.eye(x.shape[1]),standardized.T@(y-target_mean))
        predictions=((v-mean)/scale)@beta+target_mean
        model=dict(algorithm=algorithm,mean=mean.tolist(),scale=scale.tolist(),coefficients=beta.tolist(),intercept=target_mean,trained_rows=len(x))
    elif algorithm=='histogram':
        tables=[];outputs=[]
        for col in range(x.shape[1]):
            edges=np.unique(np.quantile(x[:,col],[0.2,0.4,0.6,0.8]));bins=np.digitize(x[:,col],edges)
            means=[float((y[bins==b].sum()+10*target_mean)/(sum(bins==b)+10)) for b in range(len(edges)+1)]
            tables.append(dict(edges=edges.tolist(),means=means))
            outputs.append(np.array(means)[np.digitize(v[:,col],edges)])
        predictions=np.mean(outputs,axis=0)
        model=dict(algorithm=algorithm,mean=mean.tolist(),scale=scale.tolist(),tables=tables,trained_rows=len(x))
    else: raise ValueError('unknown_challenger')
    return dict(predictions=predictions.tolist(),model=model)


def evaluate_challengers(dataset) -> dict:
    bars=dataset.bars;x=[];y=[];decisions=[];outcomes=[]
    for i in range(20,len(bars)-1):
        prefix=bars[i-20:i+2]
        if any((b.timestamp-a.available_at).total_seconds()>4*86400 for a,b in zip(prefix,prefix[1:])): continue
        prices=np.array([float(b.close) for b in bars[i-20:i+1]])
        changes=prices[1:]/prices[:-1]-1
        x.append([changes[-1],changes[-5:].mean(),changes.std(),prices[-1]/prices[0]-1])
        y.append(float(bars[i+1].close/bars[i+1].open-1)-0.001)
        decisions.append(bars[i].available_at);outcomes.append(bars[i+1].available_at)
    if len(x)<80: return dict(status='INSUFFICIENT_HISTORY',examples=len(x),required=80,authority='research_only')
    features=np.array(x);targets=np.array(y);folds=purged_splits(decisions,outcomes)
    scores={};artifacts={}
    for algorithm in ['ridge','histogram']:
        errors=[];baseline_errors=[];sample_count=0
        for train,valid in folds:
            if len(train)<10: continue
            result=fit_challenger(features[train],targets[train],features[valid],algorithm=algorithm)
            predicted=np.array(result['predictions'])
            errors.extend(((predicted-targets[valid])**2).tolist())
            baseline_errors.extend(((targets[train].mean()-targets[valid])**2).tolist())
            sample_count+=len(valid)
        scores[algorithm]=dict(samples=sample_count,mse=float(np.mean(errors)) if errors else None,
            baseline_mse=float(np.mean(baseline_errors)) if baseline_errors else None)
        artifacts[algorithm]=fit_challenger(features,targets,features[-1:],algorithm=algorithm)['model']
    return dict(status='AVAILABLE',examples=len(x),folds=len(folds),scores=scores,artifacts=artifacts,
        features=['last_return','mean_5_returns','volatility_20','momentum_20'],label='next_open_to_close_minus_declared_10bp',
        limitations=['Historical supervised label is not executed portfolio performance.','No independently observed spread/financing/borrow in this label.'],authority='research_only')
