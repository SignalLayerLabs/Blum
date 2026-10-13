"""Read the revision baked into a deployment, with a local Git fallback."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess

BUILD_REVISION = Path(__file__).parents[1] / 'data' / 'build_revision.json'


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
