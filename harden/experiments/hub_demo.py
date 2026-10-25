"""Local, model-free live replay of one audited Hub environment.

    .venvs/hub/bin/python -m harden.experiments.hub_demo

Only fixed recorded reverse-text cases can be submitted. Scores come from the
installed environment and accepted patch, through the frozen checker's workers.
No arbitrary module paths, code, environment IDs or model calls are accepted.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
import os
from pathlib import Path
import threading
import time

ROOT = Path(__file__).resolve().parents[2]
ENV_ID = 'primeintellect/reverse-text'
EVIDENCE = ROOT / 'results/evidence' / ENV_ID
PATCH = ROOT / 'patches' / ENV_ID / 'patch.py'
HOST, PORT = '127.0.0.1', 8788
LOCK = threading.Lock()


def examples():
    inspection = json.loads((EVIDENCE / 'inspection.json').read_text())
    cases = []
    for filename, label in (
        ('first-tag-only-extraction-c48a655afd.json', 'Conflicting final answers'),
        ('fuzzy-sequencematcher-ratio-9a93068c16.json', 'Incorrect near-match'),
    ):
        path = EVIDENCE / 'replays' / filename
        replay = json.loads(path.read_text())
        case = replay['cases'][0]
        row = inspection['rows'][str(case['example_index'])]
        if row['digest'] != case['example_digest']:
            raise ValueError('Saved inspection and replay digests disagree')
        cases.append({'id': replay['exploit_id'], 'label': label,
                      'exampleIndex': case['example_index'], 'digest': row['digest'],
                      'messages': row['messages'], 'gold': row['gold'],
                      'completion': case['completion'], 'reference': case['reference_completion'],
                      'verdict': case['judge']['verdict'], 'verdictReason': case['judge']['reason'],
                      'evidencePath': path.relative_to(ROOT).as_posix()})
    first = cases[0]
    cases.append({**first, 'id': 'valid-reference', 'label': 'Correct answer control',
                  'completion': first['reference'], 'verdict': 'correct',
                  'verdictReason': 'Ground-truth reference response from the recorded task.'})
    return cases


def score_case(case_id):
    from harden.audit.common import ck, load_envs
    from harden.audit.scoring import score, reward_of

    cases = {case['id']: case for case in examples()}
    if case_id not in cases:
        raise ValueError('Choose one of the recorded demo cases')
    case = cases[case_id]
    spec = load_envs()[0][ENV_ID]
    ck.WORKER_TIMEOUT_S = 30  # Per-process demo latency limit; checker source/gates unchanged.
    pairs = [(case['exampleIndex'], case['completion']), (case['exampleIndex'], case['reference'])]
    started = time.perf_counter()
    scores = {}
    for mode, patch in (('original', None), ('hardened', spec.patch_dir)):
        phase = time.perf_counter()
        out = score(spec, pairs, patch)
        if out.get('integrity') or out['digests'].get(str(case['exampleIndex'])) != case['digest']:
            raise RuntimeError('Runtime integrity or dataset digest check failed')
        reward, reference = (reward_of(out, *pair, strict=True) for pair in pairs)
        if not all(math.isfinite(v) for v in (reward, reference)) or reference <= 0:
            raise RuntimeError('Non-finite score or failing reference control')
        scores[mode] = {'reward': reward, 'referenceReward': reference,
                        'elapsedMs': round((time.perf_counter() - phase) * 1000, 2),
                        'runtimeFingerprint': out.get('fingerprint'),
                        'distributions': out.get('dists', [])}
    return {'caseId': case_id, 'environment': ENV_ID, 'mode': 'live-local-scoring',
            'scoredAt': datetime.now(timezone.utc).isoformat(), 'scores': scores,
            'exampleDigest': case['digest'], 'patchSha256': hashlib.sha256(PATCH.read_bytes()).hexdigest(),
            'elapsedMs': round((time.perf_counter() - started) * 1000, 2),
            'verdict': case['verdict'], 'verdictSource': 'saved independent audit verdict; no new model judgment',
            'modelCalls': 0, 'graphWrites': 0}


class Handler(BaseHTTPRequestHandler):
    server_version = 'LoopholeHubDemo/1'

    def respond(self, status, payload):
        blob = json.dumps(payload, allow_nan=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Length', str(len(blob)))
        self.end_headers()
        try: self.wfile.write(blob)
        except (BrokenPipeError, ConnectionResetError): pass

    def allowed(self):
        # Loopback service, only the local demo frontend may initiate browser requests.
        origin = self.headers.get('Origin')
        return origin is None or origin in ('http://127.0.0.1:5173', 'http://localhost:5173')

    def do_GET(self):
        if not self.allowed(): return self.respond(403, {'error': 'Local demo origin required'})
        if self.path != '/api/hub-demo': return self.respond(404, {'error': 'Not found'})
        try:
            self.respond(200, {'environment': ENV_ID, 'cases': examples(), 'nativeTurns': 'single',
                              'patchPath': PATCH.relative_to(ROOT).as_posix(),
                              'patchSha256': hashlib.sha256(PATCH.read_bytes()).hexdigest(),
                              'modelCalls': 0})
        except Exception as exc:
            self.respond(503, {'error': f'Demo artifacts unavailable ({type(exc).__name__})'})

    def do_POST(self):
        if not self.allowed(): return self.respond(403, {'error': 'Local demo origin required'})
        if self.path != '/api/hub-demo/score': return self.respond(404, {'error': 'Not found'})
        try:
            size = int(self.headers.get('Content-Length', '0'))
            if not 0 < size <= 512: raise ValueError('Request must contain a small case ID')
            payload = json.loads(self.rfile.read(size))
            if not isinstance(payload, dict) or set(payload) != {'caseId'} or not isinstance(payload['caseId'], str):
                raise ValueError('Expected a recorded caseId')
            if payload['caseId'] not in {c['id'] for c in examples()}: raise ValueError('Unknown caseId')
        except (ValueError, TypeError): return self.respond(400, {'error': 'Select a valid recorded case'})
        if not LOCK.acquire(blocking=False): return self.respond(409, {'error': 'A comparison is running; retry when it finishes'})
        try:
            self.respond(200, score_case(payload['caseId']))
        except Exception as exc:
            # Provider/file exception text may contain local details; never return it to the browser.
            print(f'Live scoring failed: {type(exc).__name__}', flush=True)
            self.respond(503, {'error': f'Live scoring failed ({type(exc).__name__}); inspect the installed reverse-text runtime and cached dataset. No scores were substituted.'})
        finally: LOCK.release()


def main():
    # CPU-only replay needs no model or writer secrets. Workers inherit this process env.
    for name in list(os.environ):
        if any(word in name.upper() for word in ('API_KEY', 'TOKEN', 'SECRET', 'MOSS_PROJECT_KEY')):
            os.environ.pop(name)
    os.environ.update(HF_HUB_OFFLINE='1', HF_DATASETS_OFFLINE='1', TOKENIZERS_PARALLELISM='false')
    examples()  # Fail before listening if required evidence is absent.
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f'Live Hub replay: http://{HOST}:{PORT}/api/hub-demo | reverse-text only | no model calls', flush=True)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.server_close()


if __name__ == '__main__':
    main()
