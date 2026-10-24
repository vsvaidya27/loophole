import { describe, expect, it } from 'vitest';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import * as mod from './index';
import { harness, record, seed, call, clientRows } from './graph_test_support';
import { buildGraph } from '../../dashboard/src/graph/buildGraph';

// Model responses are deterministic; storage, graph computation, Python retrieval,
// target reward evaluation, core application writes, and projection are real code.
describe('graph knowledge → Python hacker/fixer boundary → dashboard integration', () => {
  it('retrieves only independent non-seed evidence and records a validated transfer idempotently', () => {
    const t = harness(); seed(t);
    const id = record(t, 'hub/source');
    call(t, ctx => mod.record_environment(ctx, { env_id: 'hub/source', source: 'hub', title: 'Source', status: 'patched' }));
    call(t, ctx => mod.record_environment(ctx, { env_id: 'game/target', source: 'game', title: 'Target', status: 'pre_hardening' }));
    call(t, ctx => mod.rebuild_graph(ctx, {}));
    const input = {
      environments: [...t.db.environment.iter()],
      invariants: [...t.db.invariant.iter()],
      similarity_edges: [...t.db.similarity_edge.iter()],
    };
    const root = fileURLToPath(new URL('../../', import.meta.url));
    const run = spawnSync(process.env.PYTHON ?? 'python3', ['tests/retrieval_roundtrip.py'], {
      cwd: root, encoding: 'utf8', timeout: 10000,
      input: JSON.stringify(input, (_key, value) => typeof value === 'bigint' ? value.toString() : value),
    });
    expect(run.error).toBeUndefined();
    expect(run.status, run.stderr).toBe(0);
    const output = JSON.parse(run.stdout);
    expect(output.accepted).toBe(true);
    expect(output.retrieved_ids).toEqual([id]);
    expect(output.applications).toHaveLength(1);
    const app: Parameters<typeof mod.record_rule_application>[1] = output.applications[0];
    expect(app.outcome).toBe('blocked');
    const before = t.db.rule_application.count();
    call(t, ctx => mod.record_rule_application(ctx, app));
    call(t, ctx => mod.record_rule_application(ctx, app));
    expect(t.db.rule_application.count()).toBe(before + 1n);
    const graph = buildGraph(clientRows(t));
    expect(graph.edges.find(e => e.id === `applied_to:${id}->game/target`)).toMatchObject({
      source: 'rule:substring-match', target: 'env:game/target', outcome: 'blocked',
    });
    expect(graph.diagnostics).toEqual([]);
  });
});
