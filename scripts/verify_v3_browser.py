"""Network-capable CI smoke using attributed real history, never invented market rows."""
from __future__ import annotations

import csv
from datetime import datetime,time as day_time
import gzip
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
from zoneinfo import ZoneInfo

import httpx
from playwright.sync_api import sync_playwright

from blum_v3.data import accept_dataset
from blum_v3.domain import Instrument,Provenance,now
from blum_v3.storage import Repository


def main():
    root=Path(__file__).resolve().parents[1]
    web=root/'web_v3/out'
    if not (web/'index.html').is_file():raise RuntimeError('Build the web export before browser verification.')
    source=root/'backend/app/data/historical_prices_seed.csv.gz'
    with gzip.open(source,'rt') as stream:
        records=[r for r in csv.DictReader(stream) if r['ticker']=='SPY'][:120]
    rows=[];tz=ZoneInfo('America/New_York')
    for record in records:
        day=datetime.fromisoformat(record['date']).date()
        rows.append(dict(timestamp=datetime.combine(day,day_time(9,30),tz),available_at=datetime.combine(day,day_time(16),tz),
            **{key:record[key] for key in ['open','high','low','close','volume']}))
    accepted=accept_dataset(Instrument(symbol='SPY',market='equity',quote_currency='USD'),rows,
        Provenance(provider='packaged-nasdaq_api-browser-functional-check',rights='Functional research inspection; vendor redistribution entitlements not certified.',
            first_seen_at=now(),availability_policy='historical_bar_close',source_revision=hashlib.sha256(source.read_bytes()).hexdigest()))
    if len(accepted.bars)!=120:raise RuntimeError('Real historical fixture failed acceptance.')
    artifacts=root/'.artifacts/v3-browser';artifacts.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='blum-v3-browser-') as directory:
        url='sqlite:///'+str(Path(directory)/'browser.db')
        repo=Repository(url);repo.save_dataset(accepted);repo.engine.dispose()
        with socket.socket() as listener:listener.bind(('127.0.0.1',0));port=listener.getsockname()[1]
        origin=f'http://127.0.0.1:{port}'
        token='ephemeral-browser-contract-token'
        env=os.environ|{'BLUM_OPERATOR_TOKEN':token,'BLUM_WEB_PATH':str(web),'BLUM_ENV':'development','PYTHONUNBUFFERED':'1'}
        processes=[]
        with (Path(directory)/'runtime.log').open('w') as logs:
            try:
                processes.append(subprocess.Popen([sys.executable,'-m','blum_v3.cli','--database',url,'serve','--port',str(port)],cwd=root,env=env,stdout=logs,stderr=logs))
                processes.append(subprocess.Popen([sys.executable,'-m','blum_v3.cli','--database',url,'worker','--interval','0.2'],cwd=root,env=env,stdout=logs,stderr=logs))
                with httpx.Client(base_url=origin,timeout=2) as client:
                    for _ in range(80):
                        try:
                            if client.get('/health').status_code==200:break
                        except httpx.HTTPError:pass
                        time.sleep(.2)
                    else:raise RuntimeError('Browser API did not become ready.')
                    with sync_playwright() as playwright:
                        browser=playwright.chromium.launch(headless=True)
                        page=browser.new_page(viewport={'width':1440,'height':1100})
                        errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
                        page.goto(origin,wait_until='networkidle')
                        page.get_by_label('Operator token',exact=True).fill(token)
                        page.get_by_role('button',name='Open workspace').click()
                        page.get_by_label('Hypothesis',exact=True).wait_for()
                        page.get_by_label('Hypothesis',exact=True).fill('Browser functional smoke; no trading-performance claim.')
                        page.get_by_label('Source',exact=True).select_option(accepted.dataset_id)
                        page.get_by_label('Trial family',exact=True).fill('browser-functional-check')
                        page.get_by_role('button',name='Register & run experiment').click()
                        page.get_by_text('DEVELOPMENT COMPLETE',exact=True).first.wait_for(timeout=60_000)
                        page.get_by_role('img',name='Portfolio value in USD, compared with the frozen benchmark').wait_for()
                        page.screenshot(path=str(artifacts/'research-desktop.png'),full_page=True)
                        page.get_by_role('navigation').get_by_role('button').filter(has_text='Paper portfolio').click()
                        page.get_by_label('Account name',exact=True).fill('Browser paper epoch')
                        page.get_by_role('button',name='Open paper account').click()
                        page.get_by_text('No open positions.',exact=False).wait_for()
                        accounts=client.get('/api/v3/accounts',headers={'Authorization':'Bearer '+token}).json()
                        assert len(accounts)==1 and accounts[0]['cash']=='10000' and not accounts[0]['orders']
                        page.get_by_label('Source',exact=True).select_option(accepted.dataset_id)
                        page.get_by_label('Quantity',exact=True).fill('1')
                        page.get_by_role('button',name='Submit paper order').click()
                        page.get_by_role('alert').filter(has_text='stale reference').wait_for()
                        assert client.get('/api/v3/accounts',headers={'Authorization':'Bearer '+token}).json()[0]['cash']=='10000'
                        page.screenshot(path=str(artifacts/'paper-desktop.png'),full_page=True)
                        page.set_viewport_size({'width':390,'height':844})
                        page.get_by_role('navigation').get_by_role('button').filter(has_text='Research').click()
                        assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth + 1')
                        page.screenshot(path=str(artifacts/'research-mobile.png'),full_page=True)
                        assert not errors,errors
                        browser.close()
                    receipt=dict(status='PASSED',scope='Browser functional integration; no trading-performance claim.',
                        accepted_real_bars=120,source_sha256=accepted.provenance.source_revision,
                        checks=['authenticated_connection','real_source_research_job','stored_report_and_chart','paper_account_epoch','stale_order_rejected_without_cash_change','mobile_no_horizontal_overflow','no_browser_page_errors'])
                    (artifacts/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
                    print(json.dumps(receipt,indent=2))
            finally:
                for process in processes:
                    process.terminate()
                for process in processes:
                    try:process.wait(timeout=5)
                    except subprocess.TimeoutExpired:process.kill();process.wait()


if __name__=='__main__':main()
