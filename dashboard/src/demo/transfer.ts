import report from './fixtures/ruleTransfer.json';
import retrieval from './fixtures/ruleTransferRetrieval.json';
import type { DemoData } from './data';

export { report, retrieval };
export const EVIDENCE_ROOT = 'https://github.com/vsvaidya27/loophole/blob/b39414e75bc80b72f664b45ccc67070a645b395f/results/';
export const sourceEvidence = (id: string) => {
  const [env, mechanism] = id.split('#');
  return `${EVIDENCE_ROOT}evidence/${env}/replays/${mechanism}.json`;
};

/** Keep the earlier audit data only for the explicitly separate browser learning illustration. */
export function transferGraph(data: DemoData): DemoData {
  const hubIds = new Set(data.graph_before.environments.filter(e => e.source === 'hub').map(e => e.env_id));
  const invariants = data.graph_before.invariants.filter(i => hubIds.has(i.env_id));
  const ids = new Set(invariants.map(i => i.invariant_id));
  return { ...data,
    game: { ...data.game, env_id: report.targetId, name: report.targetName },
    graph_before: { ...data.graph_before,
      environments: data.graph_before.environments.filter(e => hubIds.has(e.env_id)),
      invariants,
      rules: data.graph_before.rules.map(r => ({ ...r, member_count: invariants.filter(i => i.exploit_class === r.rule_id).length })),
      similarity_edges: data.graph_before.similarity_edges.filter(e => ids.has(e.a_id) && ids.has(e.b_id)),
    },
    retrieval: { backend: report.retrieval.backend, model: report.retrieval.model, indexed: report.retrieval.indexed_documents,
      offered_to_prompt: [report.source.invariant_id],
      matches: retrieval.matches.map(m => ({ id: m.invariant_id, env_id: m.env_id, exploit_class: m.exploit_class,
        title: m.title, defense: m.defense_pattern, score: m.score, reasons: m.reasons })),
    },
    learned: { invariants: [], similarity_edges: [] },
    rounds: [{ iteration: 1, target: report.targetId, proposed: 1, confirmed: 1, patch_accepted: true, attempts: [{
      id: report.validation.attackExample.mechanism, class: 'multi-answer', plain: 'List every number in one reply',
      why_incorrect: 'No single committed guess', secret: Number(report.validation.referenceExample.replies.at(-1)?.match(/\d+/)?.[0]),
      replies: report.validation.attackExample.replies,
      scores: { under_test: report.validation.rewardBefore, exact: report.validation.attackExample.strict,
        shipped: report.validation.rewardBefore, hardened: report.validation.rewardAfter }, confirmed: true,
    }] }, { iteration: 2, target: report.targetId, proposed: 0, confirmed: 0, patch_accepted: false, attempts: [] }],
  };
}
