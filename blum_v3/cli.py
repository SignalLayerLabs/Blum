"""Operator commands. Broker execution is intentionally absent."""
import argparse
import json
import os
from pathlib import Path
import time

from .domain import now
from .storage import Repository


def main():
    parser=argparse.ArgumentParser(prog='blum',description='Blum research and paper operator')
    parser.add_argument('--database',default=os.environ.get('BLUM_DATABASE_URL','sqlite:///var/blum-v3.db'))
    commands=parser.add_subparsers(dest='command',required=True)
    serve=commands.add_parser('serve');serve.add_argument('--host',default='127.0.0.1');serve.add_argument('--port',type=int,default=7860)
    worker=commands.add_parser('worker');worker.add_argument('--once',action='store_true');worker.add_argument('--interval',type=float,default=5);worker.add_argument('--refresh-sources',action='store_true')
    ingest=commands.add_parser('import');ingest.add_argument('path')
    history=commands.add_parser('history');history.add_argument('symbol');history.add_argument('--market',choices=['equity','forex'],required=True);history.add_argument('--days',type=int,default=365)
    for command in ['archive','restore','legacy-import']:
        commands.add_parser(command).add_argument('path')
    commands.add_parser('status')
    args=parser.parse_args()
    repo=Repository(args.database,production=os.environ.get('BLUM_ENV')=='production')
    if args.command=='serve':
        import uvicorn
        from .api import create_app
        uvicorn.run(create_app(repository=repo),host=args.host,port=args.port)
    elif args.command=='worker':
        from .worker import Worker
        from .jobs import JobService
        from .paper import PaperService
        runner=Worker(repo);jobs=JobService(repo)
        if not 0.1<=args.interval<=60:parser.error('interval must be 0.1 to 60 seconds')
        while True:
            if not args.once:
                epoch=int(time.time());jobs.enqueue('paper_cycle',{},key='scheduled-paper:'+str(epoch//60))
                if args.refresh_sources:
                    symbols={(s['instrument']['symbol'],s['instrument']['market']) for s in PaperService(repo).list() if s['status']=='ACTIVE'}
                    for symbol,market in sorted(symbols)[:25]:
                        jobs.enqueue('history',dict(symbol=symbol,market=market,range_days=90),key=f'scheduled-source:{symbol}:{market}:{epoch//3600}')
            worked=runner.run_once()
            if args.once:break
            if not worked:time.sleep(args.interval)
    elif args.command=='import':
        from .api import DatasetInput
        from .data import accept_dataset
        body=DatasetInput.model_validate_json(Path(args.path).read_text());value=accept_dataset(body.instrument,body.rows,body.provenance);repo.save_dataset(value)
        print(json.dumps(dict(dataset_id=value.dataset_id,accepted=len(value.bars),rejected=len(value.rejected))))
    elif args.command=='history':
        from .jobs import JobService
        print(json.dumps(JobService(repo).enqueue('history',dict(symbol=args.symbol,market=args.market,range_days=args.days),key='history:'+now().isoformat())))
    elif args.command in {'archive','restore','legacy-import'}:
        from .archive import export_archive,restore_archive,import_legacy_evidence
        result={'archive':export_archive,'restore':restore_archive,'legacy-import':import_legacy_evidence}[args.command](repo,args.path)
        print(json.dumps(result))
    else:
        from .jobs import JobService
        from .portfolio import PortfolioService
        print(json.dumps(dict(application='Blum',version='3.0.0',database=repo.engine.dialect.name,datasets=len(repo.list_datasets()),accounts=len(PortfolioService(repo).list_accounts()),jobs=JobService(repo).list())))


if __name__=='__main__':main()
