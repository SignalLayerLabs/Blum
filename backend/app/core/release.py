"""Read the revision baked into a deployment, with a local Git fallback."""
from __future__ import annotations

import json
import hashlib
from functools import lru_cache
import os
from pathlib import Path
import re
import subprocess

BUILD_REVISION = Path(__file__).parents[1] / 'data' / 'build_revision.json'


def content_hash_for_root(root: Path) -> str:
    """Fingerprint protected runtime code, independently of declared revision variables."""
    files = [*root.joinpath('backend/app').rglob('*.py'),
             *root.joinpath('scripts').rglob('*.py'),
             *root.joinpath('scripts').rglob('*.sh')]
    result = hashlib.sha256()
    for file in sorted(set(files), key=lambda path: path.relative_to(root).as_posix()):
        relative = file.relative_to(root).as_posix().encode()
        content = file.read_bytes()
        result.update(len(relative).to_bytes(8, 'big'))
        result.update(relative)
        result.update(len(content).to_bytes(8, 'big'))
        result.update(content)
    return result.hexdigest()


@lru_cache(maxsize=1)
def source_content_hash() -> str:
    return content_hash_for_root(Path(__file__).parents[3])


def source_revision() -> str:
    if BUILD_REVISION.is_file():
        try:
            baked = json.loads(BUILD_REVISION.read_text()).get('source_revision', '')
            if re.fullmatch(r'[0-9a-f]{40}', baked):
                return baked
        except (OSError, ValueError, TypeError):
            pass
        return 'unavailable'
    configured = os.environ.get('BLUM_SOURCE_REVISION', '')
    if re.fullmatch(r'[0-9a-f]{40}', configured):
        return configured
    try:
        revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=Path(__file__).parents[3],
            stderr=subprocess.DEVNULL, timeout=2, env={'PATH': os.defpath}).decode().strip()
        return revision if re.fullmatch(r'[0-9a-f]{40}', revision) else 'unavailable'
    except (OSError, subprocess.SubprocessError):
        return 'unavailable'
