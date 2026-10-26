"""Authenticated research commands and read-only financial projections."""
from __future__ import annotations

from datetime import datetime
import hmac
import os
from pathlib import Path
from typing import Literal

from fastapi import Depends,FastAPI,Header,HTTPException,Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import Field

from . import __version__
from .data import accept_dataset
from .domain import Contract,Instrument,Provenance,RiskProfile,now,decimal
from .jobs import JobService
from .portfolio import PortfolioService
from .paper import PaperService
from .research import ResearchService
from .storage import Repository
from .security import RequestBodyLimit
from .conversion import resolve_conversion


class DatasetInput(Contract):
    instrument: Instrument
    provenance: Provenance
    rows: list[dict] = Field(max_length=250000)


class ExperimentInput(Contract):
    dataset_id: str
    config: dict = {}
    family_id: str = Field(min_length=1,max_length=100)
    hypothesis: str = Field(min_length=1,max_length=2000)


class AccountInput(Contract):
    name: str = Field(min_length=1,max_length=100)
    market: Literal['equity','forex']
    currency: str = Field(min_length=3,max_length=3)
    cash: str
    risk: RiskProfile = RiskProfile()


class OrderInput(Contract):
    dataset_id: str
    side: Literal['BUY','SELL']
    quantity: str
    kind: Literal['MARKET','LIMIT','STOP','STOP_LIMIT']='MARKET'
    limit_price: str | None=None
    stop_price: str | None=None
    expires_at: datetime | None=None
    reduce_only: bool=False
    conversion_dataset_id: str | None=None


class HistoryInput(Contract):
    symbol: str
    market: Literal['equity','forex']
    range_days: int = Field(default=365,ge=30,le=3650)


class SubscriptionInput(Contract):
    account_id: str
    experiment_id: str


def create_app(*,repository: Repository | None=None,token: str | None=None,clock=now):
    repository=repository or Repository(os.environ.get('BLUM_DATABASE_URL','sqlite:///var/blum-v3.db'),production=os.environ.get('BLUM_ENV')=='production')
    secret=token if token is not None else os.environ.get('BLUM_OPERATOR_TOKEN','')
    if not secret:raise ValueError('BLUM_OPERATOR_TOKEN_required')
    app=FastAPI(title='Blum Research & Paper',version=__version__,docs_url=None,redoc_url=None,openapi_url=None)
    portfolios=PortfolioService(repository,clock=clock);research=ResearchService(repository);jobs=JobService(repository,clock=clock)
    app.state.repository=repository
    app.add_middleware(RequestBodyLimit,limit=25_000_000)

    def authorized(authorization: str | None=Header(default=None)):
        if authorization is None or not hmac.compare_digest(authorization.encode(),('Bearer '+secret).encode()):raise HTTPException(401,'authentication_required')

    def idempotency(idempotency_key: str=Header(min_length=1,max_length=128)):
        return idempotency_key

    @app.middleware('http')
    async def bounded_request(request: Request,call_next):
        response=await call_next(request)
        response.headers['Cache-Control']='no-store'
        response.headers['X-Content-Type-Options']='nosniff'
        response.headers['Referrer-Policy']='same-origin'
        return response

    @app.exception_handler(KeyError)
    async def missing(request,error):return JSONResponse(status_code=404,content={'detail':str(error.args[0])})

    @app.exception_handler(ValueError)
    async def invalid(request,error):
        message=str(error)
        safe=message if len(message)<150 and all(c.isalnum() or c in '_- ' for c in message) else 'invalid_financial_request'
        return JSONResponse(status_code=409 if 'conflict' in safe else 422,content={'detail':safe})

    @app.get('/health')
    def health():return dict(status='ready',version=__version__,mode='research_and_paper',broker_execution=False)

    private=[Depends(authorized)]

    @app.get('/api/v3/schema',dependencies=private)
    def schema():return app.openapi()

    @app.get('/api/v3/datasets',dependencies=private)
    def list_datasets():return repository.list_datasets()

    @app.get('/api/v3/datasets/{dataset_id}',dependencies=private)
    def dataset(dataset_id: str):
        source=repository.dataset(dataset_id)
        return dict(dataset_id=source.dataset_id,instrument=source.instrument,provenance=source.provenance,accepted=len(source.bars),
            rejected=source.rejected,warnings=source.warnings,duplicate_count=source.duplicate_count,evidence_tier=source.evidence_tier)

    @app.post('/api/v3/datasets',dependencies=private,status_code=201)
    def import_dataset(body: DatasetInput):
        source=accept_dataset(body.instrument,body.rows,body.provenance);repository.save_dataset(source)
        return dict(dataset_id=source.dataset_id,accepted=len(source.bars),rejected=len(source.rejected),warnings=source.warnings)

    @app.post('/api/v3/history',dependencies=private,status_code=202)
    def history(body: HistoryInput,key: str=Depends(idempotency)):return jobs.enqueue('history',body.model_dump(),key=key)

    @app.get('/api/v3/experiments',dependencies=private)
    def experiments():return research.list()

    @app.get('/api/v3/experiments/{experiment_id}',dependencies=private)
    def experiment(experiment_id: str):return research.get(experiment_id)

    @app.post('/api/v3/experiments',dependencies=private,status_code=202)
    def register_experiment(body: ExperimentInput,key: str=Depends(idempotency)):
        value=research.create(body.dataset_id,body.config,family_id=body.family_id,key=key,hypothesis=body.hypothesis)
        return dict(experiment=value,job=jobs.enqueue('research',{'experiment_id':value['id']},key='research:'+value['id']))

    @app.post('/api/v3/experiments/{experiment_id}/confirmation',dependencies=private,status_code=202)
    def confirmation(experiment_id: str,key: str=Depends(idempotency)):
        research.get(experiment_id)
        return jobs.enqueue('confirmation',{'experiment_id':experiment_id},key=key)

    @app.get('/api/v3/accounts',dependencies=private)
    def accounts():return portfolios.list_accounts()

    @app.get('/api/v3/accounts/{account_id}',dependencies=private)
    def account(account_id: str):return portfolios.snapshot(account_id)

    @app.get('/api/v3/accounts/{account_id}/journal',dependencies=private)
    def journal(account_id: str):
        portfolios.snapshot(account_id)
        return portfolios.journal(account_id)

    @app.post('/api/v3/accounts',dependencies=private,status_code=201)
    def create_account(body: AccountInput,key: str=Depends(idempotency)):
        return portfolios.open_account(**body.model_dump(exclude={'risk'}),risk=body.risk.model_dump(mode='json'),key=key)

    @app.post('/api/v3/accounts/{account_id}/orders',dependencies=private,status_code=201)
    def order(account_id: str,body: OrderInput,key: str=Depends(idempotency)):
        source=repository.dataset(body.dataset_id);visible=[b for b in source.bars if b.available_at<=clock()]
        if not visible:raise ValueError('no_observable_market_reference')
        bar=visible[-1];account=portfolios.snapshot(account_id);fx=None
        fx=resolve_conversion(repository,source.instrument,account['currency'],clock(),preferred=body.conversion_dataset_id)
        from decimal import ROUND_FLOOR
        price=(bar.close/source.instrument.tick_size).to_integral_value(rounding=ROUND_FLOOR)*source.instrument.tick_size
        return portfolios.submit_order(account_id,instrument=source.instrument,side=body.side,quantity=body.quantity,reference_price=price,
            reference_at=bar.available_at,decision_at=clock(),source_ref=source.dataset_id,key=key,
            kind=body.kind,limit_price=body.limit_price,stop_price=body.stop_price,expires_at=body.expires_at,reduce_only=body.reduce_only,fx=fx)

    @app.post('/api/v3/accounts/{account_id}/orders/{order_id}/cancel',dependencies=private)
    def cancel_order(account_id: str,order_id: str,key: str=Depends(idempotency)):return portfolios.cancel_order(account_id,order_id,key=key)

    @app.post('/api/v3/paper/subscriptions',dependencies=private,status_code=201)
    def subscribe(body: SubscriptionInput,key: str=Depends(idempotency)):return PaperService(repository,clock=clock).subscribe(body.account_id,body.experiment_id,key=key)

    @app.get('/api/v3/paper/subscriptions',dependencies=private)
    def subscriptions():return PaperService(repository,clock=clock).list()

    @app.post('/api/v3/paper/cycle',dependencies=private,status_code=202)
    def paper_cycle(key: str=Depends(idempotency)):return jobs.enqueue('paper_cycle',{},key=key)

    @app.get('/api/v3/jobs',dependencies=private)
    def list_jobs():return jobs.list()

    @app.get('/api/v3/jobs/{job_id}',dependencies=private)
    def job(job_id: str):return jobs.get(job_id)

    @app.post('/api/v3/jobs/{job_id}/cancel',dependencies=private)
    def cancel_job(job_id: str):return jobs.cancel(job_id)

    @app.get('/api/v3/overview',dependencies=private)
    def overview():
        return dict(version=__version__,datasets=repository.list_datasets(),accounts=portfolios.list_accounts(),
            experiments=research.list(),jobs=jobs.list(),generated_at=clock().isoformat(),broker_execution=False)

    @app.get('/api/v3/operations',dependencies=private)
    def operations():
        return dict(database=repository.engine.dialect.name,schema_version=1,jobs=jobs.list(),
            subscriptions=PaperService(repository,clock=clock).list(),
            capabilities=dict(default_execution='declared_bar_scenario',quote_qualified=False,broker_execution=False),
            blockers=['Quote-qualified evidence requires independently observed quotes, funding and account reconciliation.'],generated_at=clock().isoformat())

    static=Path(os.environ.get('BLUM_WEB_PATH','web_v3/out'))
    if static.is_dir():app.mount('/',StaticFiles(directory=static,html=True),name='web')
    return app
