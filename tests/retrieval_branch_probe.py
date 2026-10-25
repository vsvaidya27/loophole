"""Executed against exported real branch code by check_retrieval_branches.py."""
import json
import random
import unittest

from env_compiler.games.easy import ArithCompute
from voice_env.harden import hacker, fixer
from harden.store.knowledge_loop import KnowledgeClient, FixProposal, ReplayResult, validate_transfer
from harden.store.retrieval import GraphRetriever
from test_retrieval import FakeLLM, snapshot


class BranchIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.matches = GraphRetriever(snapshot()).retrieve('substring parser', '', target_env_id='game/target')

    def test_actual_voice_hacker_and_fixer_accept_knowledge_client(self):
        model = FakeLLM(json.dumps({'strategies': ['Try multiple candidate answers']}))
        planner = KnowledgeClient(model, self.matches)
        self.assertEqual(hacker(planner, 'Original judge', [], 1), ['Try multiple candidate answers'])
        model.reply = json.dumps({'prompt': 'Verify policy compliance before success=true'})
        self.assertEqual(fixer(planner, 'Original judge', [], []), 'Verify policy compliance before success=true')
        self.assertEqual(planner.calls, 2)
        for system, messages, _ in model.requests:
            self.assertIn('Retrieved knowledge', system)
            self.assertNotIn('SECRET', system)

    def test_actual_compiler_game_attack_and_benign_replays(self):
        original, hardened = ArithCompute(strict=False), ArithCompute(strict=True)
        tasks = [original.generate(random.Random(seed)) for seed in range(20)]
        def evaluate(candidate, match):
            target = tasks[0]
            attack = f'999 {target.answer} -999'
            return ReplayResult(
                original.reward(target.info, attack), hardened.reward(target.info, attack),
                original.reward(target.info, original.reference_completion(target)),
                hardened.reward(target.info, hardened.reference_completion(target)),
                len(tasks), sum(hardened.reward(task.info, hardened.reference_completion(task)) == 1 for task in tasks), attack)
        result = validate_transfer(FixProposal('strict parser', ('a',)), self.matches, run_id='compiler-test',
                                   target_env_id='game/target', replay=evaluate)
        self.assertTrue(result.accepted)
        self.assertEqual(result.applications[0]['outcome'], 'blocked')
        self.assertEqual(json.loads(result.applications[0]['detail'])['benign_passed'], 20)


if __name__ == '__main__':
    unittest.main(verbosity=2)
