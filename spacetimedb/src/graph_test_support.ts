import { ConnectionId, Timestamp } from 'spacetimedb';
import { createModuleTestHarness, TestAuth } from 'spacetimedb/server/test-utils';
import spacetimedb, * as mod from './index';
import fixture from '../../fixtures/invariants.sample.json';
import type { GraphRows } from '../../dashboard/src/graph/buildGraph';

const auth = TestAuth.fromJwtPayload(JSON.stringify({ iss: 'graph-tests', sub: 'writer' }), new ConnectionId(4n));
export function harness() {
  const test = createModuleTestHarness(spacetimedb, mod);
  test.clock.set(Timestamp.fromDate(new Date('2026-10-24T12:00:00Z')));
  test.withReducerTx(auth, ctx => mod.init(ctx, {}));
  return test;
}
export type Harness = ReturnType<typeof harness>;
export function call(test: Harness, fn: Parameters<Harness['withReducerTx']>[1]) { test.withReducerTx(auth, fn); }
export function vector(axis = 0) { const v = Array<number>(384).fill(0); v[axis] = 1; return v; }
export function record(test: Harness, env_id: string, exploit_id = 'e1', exploit_class = 'substring-match', embedding = vector(), embedding_model = 'all-MiniLM-L6-v2') {
  call(test, ctx => {
    mod.record_environment(ctx, { env_id, source: 'seed', title: env_id, status: 'patched' });
    mod.record_exploit(ctx, { env_id, exploit_id, exploit_class, iteration: 1, summary: 'Confirmed example exploit', sample_completion: '1 2 3', reward_original: 1, evidence_path: 'results/example.json' });
    mod.record_invariant(ctx, { env_id, exploit_id, title: `Rule for ${env_id}`, mechanism: 'Substring checks accept multiple candidate answers', root_cause: 'The reward parser is insufficiently strict', preconditions: 'An environment using substring comparison', defense_pattern: `Strict single answer parsing for ${env_id}`, evidence_path: 'results/example.json', embedding_model, embedding });
  });
  return `${env_id}#${exploit_id}`;
}
export function seed(test: Harness) {
  for (const row of fixture.environments) call(test, ctx => mod.record_environment(ctx, row));
  for (const row of fixture.entries) call(test, ctx => {
    mod.record_exploit(ctx, { env_id: row.env_id, ...row.exploit });
    mod.record_invariant(ctx, { env_id: row.env_id, exploit_id: row.exploit.exploit_id, ...row.invariant, embedding_model: row.embedding_model, embedding: row.embedding });
  });
  for (const row of fixture.applications) call(test, ctx => mod.record_rule_application(ctx, row));
}
export function snapshot(test: Harness) {
  return {
    config: [...test.db.graph_config.iter()],
    edges: [...test.db.similarity_edge.iter()].sort((a, b) => a.edge_id.localeCompare(b.edge_id)),
    rules: [...test.db.rule.iter()].sort((a, b) => a.rule_id.localeCompare(b.rule_id)),
    titles: [...test.db.rule_title.iter()],
  };
}
export function clientRows(test: Harness): GraphRows {
  return {
    environments: [...test.db.environment.iter()].map(r => ({ envId: r.env_id, source: r.source, title: r.title, status: r.status })),
    exploits: [...test.db.exploit.iter()].map(r => ({ invariantId: r.invariant_id, envId: r.env_id, exploitClass: r.exploit_class, summary: r.summary })),
    invariants: [...test.db.invariant.iter()].map(r => ({ invariantId: r.invariant_id, envId: r.env_id, exploitClass: r.exploit_class, title: r.title })),
    rules: [...test.db.rule.iter()].map(r => ({ ruleId: r.rule_id, title: r.title, memberCount: r.member_count, envCount: r.env_count })),
    similarityEdges: [...test.db.similarity_edge.iter()].map(r => ({ edgeId: r.edge_id, aId: r.a_id, bId: r.b_id, score: r.score })),
    ruleApplications: [...test.db.rule_application.iter()].map(r => ({ applicationKey: r.application_key, invariantId: r.invariant_id, targetEnvId: r.target_env_id, outcome: r.outcome, createdAt: r.created_at })),
  };
}
