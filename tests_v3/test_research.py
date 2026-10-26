from datetime import datetime, timezone, timedelta

import numpy as np
import pytest

from test_execution import dataset


def test_statistical_sampling_uses_per_observation_units():
    from blum_v3.evaluation import probabilistic_sharpe
    result=probabilistic_sharpe([1.0]*55+[-1.0]*45)
    assert result['per_observation_sharpe']==pytest.approx(0.1)
    assert 0.82<result['probability_above_reference']<0.85
    assert result['annualized_sharpe'] is None
    assert probabilistic_sharpe([0,0,0])['probability_above_reference'] is None
    with pytest.raises(ValueError): probabilistic_sharpe([float('nan'),1,2])


def test_purged_training_outcomes_do_not_cross_validation_boundary():
    from blum_v3.learning import purged_splits
    start=datetime(2024,1,1,tzinfo=timezone.utc)
    decisions=[start+timedelta(days=i) for i in range(100)]
    outcomes=[value+timedelta(days=4) for value in decisions]
    folds=purged_splits(decisions,outcomes,folds=3,embargo_days=2)
    for train,valid in folds:
        assert max(outcomes[i] for i in train)<min(decisions[i] for i in valid)-timedelta(days=2)
        assert set(train).isdisjoint(valid)


def test_challenger_preprocessing_never_fits_on_validation():
    from blum_v3.learning import fit_challenger
    x=np.array([[float(i),float(i%3)] for i in range(50)])
    y=np.array([float(i)/100 for i in range(50)])
    validation=np.array([[1000.0,0.0]])
    result=fit_challenger(x,y,validation,algorithm='ridge')
    assert result['model']['mean'][0]==pytest.approx(24.5)
    assert len(result['predictions'])==1
    assert result['model']['trained_rows']==50
    nonlinear=fit_challenger(x,y,validation,algorithm='histogram')
    assert len(nonlinear['predictions'])==1


def test_paired_uncertainty_requires_identical_clocks_and_counts_real_family():
    from blum_v3.evaluation import paired_interval
    a=[dict(at=str(i),nav=str(100+i)) for i in range(40)]
    b=[dict(at=str(i),nav='100') for i in range(40)]
    single=paired_interval(a,b,trials=1)
    family=paired_interval(a,b,trials=20)
    assert family['confidence']>single['confidence']
    assert family['lower_percent']<=single['lower_percent']
    assert paired_interval(a,b[:-1],trials=1)['status']=='UNAVAILABLE'


def test_experiments_freeze_inputs_count_trials_and_keep_holdout_closed(tmp_path):
    from blum_v3.storage import Repository
    from blum_v3.research import ResearchService
    repository=Repository('sqlite:///'+str(tmp_path/'r.db'))
    source=dataset(length=40); repository.save_dataset(source)
    service=ResearchService(repository)
    first=service.create(source.dataset_id,dict(lookback=3),family_id='family',key='first')
    second=service.create(source.dataset_id,dict(lookback=4),family_id='family',key='second')
    assert first['frozen_hash']!=second['frozen_hash']
    result=service.run(first['id'])
    assert result['holdout']['opened'] is False
    assert result['family_trial_count']==2
    assert result['report']['curve'][-1]['at']<result['holdout']['first_available_at']
    assert service.run(first['id'])['report']['fingerprint']==result['report']['fingerprint']
    with pytest.raises(ValueError,match='idempotency_conflict'):
        service.create(source.dataset_id,dict(lookback=7),family_id='family',key='first')
    confirmed=service.confirm(first['id'])
    assert confirmed['holdout']['opened'] is True
    assert confirmed['confirmation']['scope'].startswith('Historical')
    assert service.confirm(first['id'])['confirmation']['fingerprint']==confirmed['confirmation']['fingerprint']


def test_empty_and_tiny_dataset_cannot_be_a_successful_experiment(tmp_path):
    from blum_v3.storage import Repository
    from blum_v3.research import ResearchService
    repository=Repository('sqlite:///'+str(tmp_path/'r.db'));source=dataset(length=3);repository.save_dataset(source)
    with pytest.raises(ValueError,match='minimum_history'):
        ResearchService(repository).create(source.dataset_id,{},family_id='small',key='small')
