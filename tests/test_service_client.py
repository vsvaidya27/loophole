import io
import json
import unittest
from pathlib import Path
from unittest.mock import patch
from harden.store.service_client import ServiceClient


class ServiceClientTests(unittest.TestCase):
    def test_fixture_matches_reducer_positional_order_and_graph_notification(self):
        fixture = json.loads((Path(__file__).resolve().parents[1] / 'fixtures/invariants.sample.json').read_text())
        calls = []
        def send(request, **kwargs):
            calls.append((request.full_url.rsplit('/', 1)[-1], json.loads(request.data)))
            self.assertEqual(request.get_header('Authorization'), 'Bearer writer-token')
            return io.BytesIO(b'')
        with patch('harden.store.service_client.urlopen', side_effect=send):
            ServiceClient('https://example.invalid', 'graph', 'writer-token').push(fixture)
        first = fixture['entries'][0]
        index = next(i for i, call in enumerate(calls) if call[0] == 'record_exploit')
        self.assertEqual([c[0] for c in calls[index:index + 3]], ['record_exploit', 'record_invariant', 'graph_on_invariant'])
        self.assertEqual(calls[index + 1][1][:2], [first['env_id'], first['exploit']['exploit_id']])
        self.assertEqual(calls[index + 2][1], [first['env_id'] + '#' + first['exploit']['exploit_id']])
        self.assertEqual(sum(c[0] == 'graph_on_invariant' for c in calls), 12)

    def test_errors_propagate_and_no_write_without_token(self):
        with self.assertRaises(ValueError): ServiceClient('https://example.invalid', 'graph', '')
        with patch('harden.store.service_client.urlopen', side_effect=TimeoutError('offline')):
            with self.assertRaises(TimeoutError): ServiceClient('https://example.invalid', 'graph', 'token').call('rebuild_graph')

    def test_application_dict_becomes_versioned_json_argument(self):
        with patch('harden.store.service_client.urlopen', return_value=io.BytesIO(b'')) as send:
            ServiceClient('https://example.invalid', 'graph', 'token').call('record_rule_application',
                run_id='run', invariant_id='a#1', target_env_id='game/b', outcome='blocked', detail={'v': 1})
        self.assertEqual(json.loads(send.call_args.args[0].data), ['run', 'a#1', 'game/b', 'blocked', '{"v": 1}'])

if __name__ == '__main__':
    unittest.main()
