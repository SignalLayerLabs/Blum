"""Supervise the API and paper worker as one production runtime."""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import time

from .storage import Repository


def runtime_configuration(environment):
    env=dict(environment)
    key=env.get('BLUM_OPERATOR_TOKEN') or env.get('BLUM_ASCENT_ADMIN_KEY')
    if not key:raise ValueError('operator_key_required')
    url=env.get('BLUM_DATABASE_URL') or env.get('DATABASE_URL','')
    if not url.startswith('postgresql'):raise ValueError('production_requires_postgresql')
    env.update(BLUM_OPERATOR_TOKEN=key,BLUM_DATABASE_URL=url.replace('postgresql+psycopg2://','postgresql+psycopg://',1),
        BLUM_ENV='production',BLUM_WEB_PATH=env.get('BLUM_WEB_PATH','/app/web_v3/out'))
    return env


def supervise(commands,env,*,spawn=subprocess.Popen):
    children=[]
    def stop(signum,frame):raise KeyboardInterrupt
    previous={kind:signal.signal(kind,stop) for kind in [signal.SIGTERM,signal.SIGINT]}
    result=1
    try:
        for index,command in enumerate(commands):
            child=spawn(command,env=env);children.append(child)
            if index==0:env={**env,'BLUM_WORKER_PID':str(child.pid)}
        while all(child.poll() is None for child in children):time.sleep(.1)
    except KeyboardInterrupt:result=0
    finally:
        for child in children:
            if child.poll() is None:child.terminate()
        for child in children:
            try:child.wait(timeout=10)
            except subprocess.TimeoutExpired:child.kill();child.wait()
        for kind,handler in previous.items():signal.signal(kind,handler)
    return result


def main():
    env=runtime_configuration(os.environ)
    # Initialize schema before starting two processes, avoiding concurrent DDL.
    repository=Repository(env['BLUM_DATABASE_URL'],production=True);repository.engine.dispose()
    commands=[[sys.executable,'-m','blum_v3.cli','worker','--refresh-sources'],
        [sys.executable,'-m','blum_v3.cli','serve','--host','0.0.0.0','--port',env.get('PORT','7860')]]
    raise SystemExit(supervise(commands,env))


if __name__=='__main__':main()
