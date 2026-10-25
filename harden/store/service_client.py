"""Small HTTP writer for the hosted knowledge graph; no model dependencies.

python -m harden.store.service_client push audit-batch.json
Reads SPACETIME_HOST, SPACETIME_DB and SPACETIME_TOKEN (or SPACETIME_TOKEN_FILE).
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

ARGS = {
    'record_environment': ('env_id', 'source', 'title', 'status'),
    'record_exploit': ('env_id', 'exploit_id', 'exploit_class', 'iteration', 'summary', 'sample_completion', 'reward_original', 'evidence_path'),
    'record_invariant': ('env_id', 'exploit_id', 'title', 'mechanism', 'root_cause', 'preconditions', 'defense_pattern', 'evidence_path', 'embedding_model', 'embedding'),
    'mark_exploit_patched': ('env_id', 'exploit_id', 'reward_patched'),
    'record_rule_application': ('run_id', 'invariant_id', 'target_env_id', 'outcome', 'detail'),
    'graph_on_invariant': ('invariant_id',),
    'rebuild_graph': (),
    'clear_environment': ('env_id',),
}


class ServiceClient:
    def __init__(self, host: str, database: str, token: str, *, timeout=30):
        if not token.strip():
            raise ValueError('An authorized writer token is required')
        self.base = host.rstrip('/') + '/v1/database/' + quote(database, safe='')
        self.token, self.timeout = token.strip(), timeout

    def call(self, reducer: str, **fields):
        names = ARGS[reducer]
        args = [fields[name] for name in names]
        if reducer == 'record_rule_application' and isinstance(args[-1], dict):
            args[-1] = json.dumps(args[-1])
        request = Request(self.base + '/call/' + reducer, data=json.dumps(args, allow_nan=False).encode(),
                          headers={'Authorization': 'Bearer ' + self.token, 'Content-Type': 'application/json'}, method='POST')
        try:
            with urlopen(request, timeout=self.timeout) as response:
                response.read()
        except HTTPError as error:
            detail = error.read().decode(errors='replace')[:2000]
            raise RuntimeError(f'{reducer}: HTTP {error.code}: {detail}') from None

    def push(self, batch: dict):
        """Push one fixture-shaped batch. Repeating the same batch safely retries it.

        A partial failure propagates: do not mark SQLite pushed until this returns.
        All environments must be included or already exist in the database.
        """
        for row in batch.get('environments', []):
            self.call('record_environment', **row)
        for entry in batch.get('entries', []):
            env = entry['env_id']
            exploit = entry['exploit']
            self.call('record_exploit', env_id=env, **exploit)
            self.call('record_invariant', env_id=env, exploit_id=exploit['exploit_id'],
                      **entry['invariant'], embedding_model=entry.get('embedding_model', ''),
                      embedding=entry.get('embedding', []))
            self.call('graph_on_invariant', invariant_id=f"{env}#{exploit['exploit_id']}")
            if exploit.get('reward_patched') is not None:
                self.call('mark_exploit_patched', env_id=env, exploit_id=exploit['exploit_id'], reward_patched=exploit['reward_patched'])
        for row in batch.get('applications', []):
            self.call('record_rule_application', **row)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['push'])
    parser.add_argument('batch', type=Path)
    args = parser.parse_args()
    token = os.environ.get('SPACETIME_TOKEN', '')
    if not token and os.environ.get('SPACETIME_TOKEN_FILE'):
        token = Path(os.environ['SPACETIME_TOKEN_FILE']).read_text().strip()
    client = ServiceClient(os.environ['SPACETIME_HOST'], os.environ['SPACETIME_DB'], token)
    client.push(json.loads(args.batch.read_text()))
    print('Batch pushed successfully, including graph notifications.')


if __name__ == '__main__':
    main()
