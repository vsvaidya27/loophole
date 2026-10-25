"""OS-isolated execution of generated modules on macOS; fail closed elsewhere."""
from __future__ import annotations
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]

def run_worker(module: str, args: list[str], read_paths: list[Path], *, timeout=120):
    executable = shutil.which('sandbox-exec')
    if sys.platform != 'darwin' or not executable:
        raise RuntimeError('Generated-code execution requires macOS sandbox-exec; configure a container runner on this platform')
    with tempfile.TemporaryDirectory(prefix='loophole-isolated-') as folder:
        scratch = Path(folder).resolve()
        allowed = [ROOT / 'env_compiler', Path(sys.prefix).resolve(), Path(sys.base_prefix).resolve(),
                   scratch, *(p.resolve() for p in read_paths)]
        # Home reads are denied except the code/runtime directories actually needed.
        exceptions = f'(require-not (literal {json.dumps(str(ROOT))})) ' + ' '.join(f'(require-not (subpath {json.dumps(str(path))}))' for path in allowed)
        profile = f'''(version 1) (allow default) (deny network*) (deny process-fork)
        (deny file-read-data (require-all (subpath {json.dumps(str(Path.home()))}) {exceptions}))
        (deny file-write* (require-not (subpath {json.dumps(str(scratch))})))'''
        env = {'PATH': os.environ.get('PATH', ''), 'PYTHONPATH': str(ROOT), 'PYTHONDONTWRITEBYTECODE': '1',
               'HOME': str(scratch), 'TMPDIR': str(scratch)}
        process = subprocess.Popen([executable, '-p', profile, sys.executable, '-m', module, *args],
            cwd=scratch, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)
        try: stdout, stderr = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL); process.communicate()
            raise subprocess.TimeoutExpired(module, timeout)
        return subprocess.CompletedProcess(process.args, process.returncode, stdout, stderr)
