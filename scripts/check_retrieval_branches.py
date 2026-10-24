"""Check actual compiler and voice-loop APIs from another branch without merging it.

python scripts/check_retrieval_branches.py --ref origin/integration
Requires the other branch's import dependency httpx; no API keys or model calls.
"""
import argparse
import io
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile

root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--ref', default='origin/integration')
args = parser.parse_args()
commit = subprocess.check_output(['git', 'rev-parse', '--verify', args.ref + '^{commit}'], cwd=root, text=True).strip()
archive = subprocess.check_output(['git', 'archive', commit, 'env_compiler', 'voice_env'], cwd=root)
with tempfile.TemporaryDirectory(prefix='loophole-retrieval-') as tmp:
    with tarfile.open(fileobj=io.BytesIO(archive)) as files:
        files.extractall(tmp, filter='data')
    env = dict(os.environ, PYTHONPATH=os.pathsep.join([tmp, str(root), str(root / 'tests')]), PYTHONDONTWRITEBYTECODE='1')
    result = subprocess.run([sys.executable, str(root / 'tests/retrieval_branch_probe.py')], cwd=tmp, env=env)
    if result.returncode:
        sys.exit(result.returncode)
print(f'Cross-branch retrieval checks passed against {args.ref} ({commit}).')
