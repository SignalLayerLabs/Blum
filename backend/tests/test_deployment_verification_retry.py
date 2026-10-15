"""Run the production workflow's verification shell against controlled transient failures."""
import os
from pathlib import Path
import subprocess

import pytest


def verification_script():
    workflow = (Path(__file__).parents[2] / '.github/workflows/deploy.yml').read_text()
    lines = workflow.split('      - name: Verify public release\n', 1)[1].splitlines()
    instruction = lines[0].strip().removeprefix('run: ')
    if instruction != '|':
        return instruction
    return '\n'.join(line[10:] for line in lines[1:] if line.startswith('          '))


@pytest.mark.parametrize('failures,expected_status,attempts', [(2, 0, 3), (99, 1, 3)])
def test_verification_retries_transient_failures_but_never_accepts_a_persistent_failure(tmp_path, failures, expected_status, attempts):
    fake = tmp_path / 'bin'
    fake.mkdir()
    verifier = fake / 'python'
    verifier.write_text('''#!/bin/sh
case "$*" in 'scripts/verify_deployment.py --timeout 120') ;; *) exit 99;; esac
count=0
[ ! -f "$BLUM_TEST_COUNT" ] || count=$(cat "$BLUM_TEST_COUNT")
count=$((count+1))
printf '%s' "$count" > "$BLUM_TEST_COUNT"
[ "$count" -gt "$BLUM_TEST_FAILURES" ]
''')
    verifier.chmod(0o700)
    sleeper = fake / 'sleep'
    sleeper.write_text('#!/bin/sh\nexit 0\n')
    sleeper.chmod(0o700)
    count = tmp_path / 'attempts'
    env = {**os.environ, 'PATH': str(fake) + ':/usr/bin:/bin', 'BLUM_TEST_COUNT': str(count), 'BLUM_TEST_FAILURES': str(failures)}
    result = subprocess.run(['/bin/bash', '-e', '-c', verification_script()], env=env, capture_output=True, text=True, timeout=10)
    assert result.returncode == expected_status, result.stdout + result.stderr
    assert int(count.read_text()) == attempts
