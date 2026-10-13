"""One-way, fast-forward-only publication of canonical Git source to the Space."""
import os
from pathlib import Path
import subprocess
import tempfile

from huggingface_hub import HfApi

ROOT = Path(__file__).resolve().parents[1]
token = os.environ.get('HF_TOKEN', '')
if not token:
    raise SystemExit('Configure HF_TOKEN in the GitHub production environment.')
revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
api = HfApi(token=token)
api.add_space_variable(repo_id='Italianhype/Blum', key='BLUM_SOURCE_REVISION', value=revision)
remote = 'https://huggingface.co/spaces/Italianhype/Blum'
with tempfile.TemporaryDirectory(prefix='blum-deploy-') as directory:
    askpass = Path(directory) / 'askpass.py'
    askpass.write_text("#!/usr/bin/env python3\nimport os,sys\nprint('Italianhype' if 'username' in sys.argv[1].lower() else os.environ['HF_TOKEN'])\n")
    askpass.chmod(0o700)
    env = {**os.environ, 'GIT_ASKPASS':str(askpass), 'GIT_TERMINAL_PROMPT':'0'}
    command = ['git', '-c', 'credential.helper=']
    subprocess.run([*command, 'lfs', 'push', remote, revision], cwd=ROOT, env=env, check=True)
    subprocess.run([*command, 'push', remote, revision+':refs/heads/main'], cwd=ROOT, env=env, check=True)
print('Published GitHub source to Hugging Face', revision)
