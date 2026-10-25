"""OS-isolated execution of generated modules: macOS sandbox-exec or Linux bubblewrap; fail closed elsewhere."""
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
SYSTEM_DIRS = ('/usr', '/lib', '/lib64', '/lib32', '/bin', '/sbin', '/etc')  # read-only on Linux

def run_worker(module: str, args: list[str], read_paths: list[Path], *, timeout=120):
    with tempfile.TemporaryDirectory(prefix='loophole-isolated-') as folder:
        scratch = Path(folder).resolve()
        allowed = [ROOT / 'env_compiler', Path(sys.prefix).resolve(), Path(sys.base_prefix).resolve(),
                   scratch, *(p.resolve() for p in read_paths)]
        env = {'PATH': os.environ.get('PATH', ''), 'PYTHONPATH': str(ROOT), 'PYTHONDONTWRITEBYTECODE': '1',
               'HOME': str(scratch), 'TMPDIR': str(scratch)}
        command = [sys.executable, '-m', module, *args]
        if sys.platform == 'darwin' and shutil.which('sandbox-exec'):
            command = _sandbox_exec(command, allowed, scratch)
        elif sys.platform.startswith('linux') and shutil.which('bwrap'):
            command = _bubblewrap(command, allowed, scratch)
        else:
            raise RuntimeError('Generated-code execution requires macOS sandbox-exec or Linux bubblewrap (bwrap); '
                               'configure a container runner on this platform')
        process = subprocess.Popen(command, cwd=scratch, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   text=True, start_new_session=True)
        try: stdout, stderr = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL); process.communicate()
            raise subprocess.TimeoutExpired(module, timeout)
        return subprocess.CompletedProcess(process.args, process.returncode, stdout, stderr)

def _sandbox_exec(command: list[str], allowed: list[Path], scratch: Path) -> list[str]:
    # Home reads are denied except the code/runtime directories actually needed.
    exceptions = f'(require-not (literal {json.dumps(str(ROOT))})) ' + ' '.join(f'(require-not (subpath {json.dumps(str(path))}))' for path in allowed)
    profile = f'''(version 1) (allow default) (deny network*) (deny process-fork)
    (deny file-read-data (require-all (subpath {json.dumps(str(Path.home()))}) {exceptions}))
    (deny file-write* (require-not (subpath {json.dumps(str(scratch))})))'''
    return [shutil.which('sandbox-exec'), '-p', profile, *command]

def _bubblewrap(command: list[str], allowed: list[Path], scratch: Path) -> list[str]:
    """Same policy as the macOS profile, by construction: the worker sees only system directories
    (read-only), the allowed code/runtime paths (read-only) and the scratch directory (the only
    writable path). New network, PID, IPC and UTS namespaces: no network, no view of host
    processes; the caller passes exactly `env` (no API keys)."""
    args = ['bwrap', '--unshare-all', '--die-with-parent', '--new-session',
            '--proc', '/proc', '--dev', '/dev', '--tmpfs', '/tmp']
    for d in SYSTEM_DIRS:
        args += ['--ro-bind-try', d, d]
    for path in allowed:
        if path != scratch:
            args += ['--ro-bind', str(path), str(path)]
    args += ['--bind', str(scratch), str(scratch), '--remount-ro', '/', '--chdir', str(scratch)]  # writes: scratch only
    return [shutil.which('bwrap'), *args[1:], *command]
