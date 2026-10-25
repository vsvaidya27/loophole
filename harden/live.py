"""One entry point for the cost-aware live pipeline.

python -m harden.live doctor --remote
python -m harden.live start
python -m harden.live hub primeintellect/reverse-text
python -m harden.live compile 'Guess a hidden number with higher/lower feedback'
"""
from __future__ import annotations
import argparse
import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from urllib.request import urlopen
from harden.audit.llm import _load_env_file, Ledger

ROOT = Path(__file__).resolve().parents[1]

def doctor(remote=False):
    _load_env_file(ROOT)
    token_file = ROOT / os.environ.get('SPACETIME_TOKEN_FILE', '.spacetime-varun-token')
    result = {'branch': subprocess.check_output(['git', 'branch', '--show-current'], cwd=ROOT, text=True).strip(),
        'key_file': str(ROOT / '.env'), 'anthropic_key_configured': bool(os.environ.get('ANTHROPIC_API_KEY', '').strip()),
        'model': os.environ.get('ANTHROPIC_MODEL', 'claude-haiku-5-5'), 'hard_cap_usd': os.environ.get('AUDIT_HARD_CAP_USD') or None,
        'budget_warning_usd': float(os.environ.get('AUDIT_BUDGET_WARNING_USD', '2')),
        'spent_or_reserved_usd': Ledger(ROOT / 'results/spend_ledger.jsonl').total(),
        'writer_token_configured': bool(os.environ.get('SPACETIME_TOKEN')) or token_file.is_file(),
        'reverse_text_runtime': (ROOT / '.venvs/hub/bin/python').exists(),
        'embedding_package': importlib.util.find_spec('sentence_transformers') is not None,
        'dashboard_dependencies': (ROOT / 'dashboard/node_modules').is_dir(),
        'dashboard_url': 'http://127.0.0.1:5173/', 'model_calls_made_by_doctor': 0}
    state = ROOT / '.cache/live-services.json'
    if state.exists(): result['services'] = json.loads(state.read_text())
    if remote:
        from harden.store.retrieval import SpacetimeKnowledgeSource
        snapshot = SpacetimeKnowledgeSource(os.environ.get('SPACETIME_HOST', 'https://maincloud.spacetimedb.com'),
            os.environ.get('SPACETIME_DB', 'loophole-knowledge-calhacks-2026'), timeout=30).load()
        result['hosted_service'] = {'environments': len(snapshot.environments), 'invariants': len(snapshot.invariants),
                                    'similarity_edges': len(snapshot.similarity_edges), 'reachable': True}
        try:
            with urlopen('http://127.0.0.1:5173/', timeout=2) as response: result['dashboard_reachable'] = response.status == 200
        except OSError: result['dashboard_reachable'] = False
    return result

def start():
    _load_env_file(ROOT)
    from harden.store.push import configured_client
    configured_client()  # fail before starting processes if the writer is not configured
    children = []
    state_path = ROOT / '.cache/live-services.json'; state_path.parent.mkdir(exist_ok=True)
    if state_path.exists():
        old = json.loads(state_path.read_text())
        pid = old.get('supervisor_pid')
        if isinstance(pid, int):
            try: os.kill(pid, 0)
            except ProcessLookupError: pass
            else: raise RuntimeError('Live supervisor is already running; use doctor to inspect it')
    try:
        # Never give the frontend development server model/writer credentials.
        env = {key: value for key, value in os.environ.items() if not any(word in key.upper() for word in ('TOKEN', 'API_KEY', 'SECRET'))}
        try:
            with urlopen('http://127.0.0.1:5173/', timeout=2) as response: existing = response.status == 200
        except OSError: existing = False
        if not existing:
            children.append(subprocess.Popen(['npm', 'run', 'dev', '--prefix', 'dashboard'], cwd=ROOT, env=env))
        pusher = subprocess.Popen([sys.executable, '-m', 'harden.store.push', '--watch', '--embed'], cwd=ROOT)
        children.append(pusher)
        state_path.write_text(json.dumps({'supervisor_pid': os.getpid(), 'pusher_pid': pusher.pid,
            'dashboard': 'existing' if existing else children[0].pid, 'model_calls_started': False}))
        print('Live dashboard: http://127.0.0.1:5173/ | SQLite pusher running | no model job auto-started', flush=True)
        while True:
            for child in children:
                if child.poll() is not None: raise RuntimeError(f'Service exited with status {child.returncode}')
            time.sleep(1)
    finally:
        for child in children:
            if child.poll() is None: child.terminate()
        for child in children:
            try: child.wait(timeout=5)
            except subprocess.TimeoutExpired: child.kill(); child.wait()
        state_path.unlink(missing_ok=True)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    check = sub.add_parser('doctor'); check.add_argument('--remote', action='store_true')
    sub.add_parser('start')
    hub = sub.add_parser('hub'); hub.add_argument('env_id', nargs='?', default='primeintellect/reverse-text')
    hub.add_argument('--rounds', type=int, default=2)
    compiler = sub.add_parser('compile'); compiler.add_argument('description')
    sub.add_parser('sync')
    args = parser.parse_args()
    _load_env_file(ROOT)
    if args.command == 'doctor': print(json.dumps(doctor(args.remote), indent=2)); return 0
    if args.command == 'start':
        try: start()
        except KeyboardInterrupt: pass
        return 0
    if args.command == 'hub':
        return subprocess.call([sys.executable, '-m', 'harden.audit.pilot_loop', args.env_id, '--rounds', str(args.rounds)], cwd=ROOT)
    if args.command == 'compile':
        return subprocess.call([sys.executable, '-m', 'harden.experiments.generated_pilot', args.description], cwd=ROOT)
    return subprocess.call([sys.executable, '-m', 'harden.store.push', '--sync', '--embed'], cwd=ROOT)

if __name__ == '__main__': raise SystemExit(main())
