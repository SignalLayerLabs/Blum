"""Public deployment identity and bounded readiness; contains no account data."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re

from sqlalchemy import text
from . import __version__

ROOT=Path(__file__).resolve().parents[1]


def release_identity(root: Path=ROOT):
    revision='unavailable'
    try:
        baked=json.loads((root/'blum_v3/build_revision.json').read_text()).get('source_revision','')
        if re.fullmatch(r'[0-9a-f]{40}',baked):revision=baked
    except (OSError,ValueError,TypeError):pass
    files=[*root.joinpath('blum_v3').glob('*.py'),*root.joinpath('scripts').rglob('*.py'),*root.joinpath('scripts').rglob('*.sh')]
    files += [p for p in [root/'Dockerfile',root/'pyproject.toml'] if p.is_file()]
    digest=hashlib.sha256()
    for file in sorted(set(files),key=lambda p:p.relative_to(root).as_posix()):
        name=file.relative_to(root).as_posix().encode();content=file.read_bytes()
        digest.update(len(name).to_bytes(8,'big'));digest.update(name)
        digest.update(len(content).to_bytes(8,'big'));digest.update(content)
    return dict(version=__version__,source_revision=revision,source_content_hash=digest.hexdigest(),mode='research_and_paper',broker_execution=False)


def readiness(repository,web_path: Path,worker_pid: str | None):
    database=False;worker=False
    try:
        with repository.engine.connect() as conn:database=conn.scalar(text('SELECT 1'))==1
    except Exception:pass
    try:
        if worker_pid and int(worker_pid)>0:os.kill(int(worker_pid),0);worker=True
    except (OSError,ValueError):pass
    return dict(api_ready=database,ui_ready=(web_path/'index.html').is_file(),worker_ready=worker,last_error=None if database else 'database_unavailable')
