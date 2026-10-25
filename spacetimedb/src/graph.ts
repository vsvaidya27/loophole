// Only reducer exports may reach index.ts. Core writes remain independent of graph writes.
import { SenderError, t } from 'spacetimedb/server';
import spacetimedb, { type Ctx } from './schema';
import { EXPLOIT_CLASSES } from './taxonomy';
import { requireWriter } from './access';

function compareText(a: string, b: string): number {
  return a < b ? -1 : a > b ? 1 : 0;
}

function ensureConfig(ctx: Ctx) {
  return ctx.db.graph_config.id.find(0) ?? ctx.db.graph_config.insert({
    id: 0, edge_threshold: 0.45, max_edges_per_node: 5,
  });
}

function recompute(ctx: Ctx): void {
  const config = ensureConfig(ctx);
  const invariants = [...ctx.db.invariant.iter()].sort((a, b) => {
    const at = a.created_at.microsSinceUnixEpoch;
    const bt = b.created_at.microsSinceUnixEpoch;
    return at < bt ? -1 : at > bt ? 1 : compareText(a.invariant_id, b.invariant_id);
  });
  const embeddings = new Map([...ctx.db.invariant_embedding.iter()]
    .filter(row => row.model && row.vector.length > 0 && row.vector.every(Number.isFinite)
      && row.vector.some(value => value !== 0))
    .map(row => [row.invariant_id, row]));
  const wantedEdges = new Map<string, {
    edge_id: string; a_id: string; b_id: string; score: number;
  }>();

  // Recompute the bounded earlier-neighbour graph so edits, deletions and out-of-order
  // pusher retries produce exactly the same result as sync/rebuild. Hundreds of rows
  // are small enough for this O(n² * embedding dimension) operation.
  for (let i = 0; i < invariants.length; i += 1) {
    const current = invariants[i];
    const embedding = embeddings.get(current.invariant_id);
    if (!embedding || config.max_edges_per_node === 0) continue;
    const candidates: { id: string; score: number }[] = [];
    for (let j = 0; j < i; j += 1) {
      const previous = invariants[j];
      const other = embeddings.get(previous.invariant_id);
      if (!other || other.model !== embedding.model || other.vector.length !== embedding.vector.length) continue;
      let dot = 0;
      let normA = 0;
      let normB = 0;
      for (let k = 0; k < embedding.vector.length; k += 1) {
        dot += embedding.vector[k] * other.vector[k];
        normA += embedding.vector[k] ** 2;
        normB += other.vector[k] ** 2;
      }
      const score = Math.fround(Math.max(-1, Math.min(1, dot / Math.sqrt(normA * normB))));
      if (Number.isFinite(score) && score >= config.edge_threshold) candidates.push({ id: previous.invariant_id, score });
    }
    candidates.sort((a, b) => b.score - a.score || compareText(a.id, b.id));
    for (const candidate of candidates.slice(0, config.max_edges_per_node)) {
      const [a_id, b_id] = [current.invariant_id, candidate.id].sort(compareText);
      const edge_id = `${a_id}|${b_id}`;
      wantedEdges.set(edge_id, { edge_id, a_id, b_id, score: candidate.score });
    }
  }
  for (const row of [...ctx.db.similarity_edge.iter()]) {
    if (!wantedEdges.has(row.edge_id)) ctx.db.similarity_edge.edge_id.delete(row.edge_id);
  }
  for (const row of wantedEdges.values()) {
    const old = ctx.db.similarity_edge.edge_id.find(row.edge_id);
    if (!old) ctx.db.similarity_edge.insert(row);
    else if (old.score !== row.score || old.a_id !== row.a_id || old.b_id !== row.b_id) {
      ctx.db.similarity_edge.edge_id.update(row);
    }
  }

  const groups = new Map<string, typeof invariants>();
  for (const row of invariants) {
    const members = groups.get(row.exploit_class) ?? [];
    members.push(row);
    groups.set(row.exploit_class, members);
  }
  for (const row of [...ctx.db.rule.iter()]) {
    if (!groups.has(row.rule_id)) ctx.db.rule.rule_id.delete(row.rule_id);
  }
  for (const [rule_id, members] of groups) {
    const display = rule_id.replace(/-/g, ' ');
    const row = {
      rule_id,
      title: ctx.db.rule_title.rule_id.find(rule_id)?.title ?? display[0].toUpperCase() + display.slice(1),
      defense_pattern: members[0].defense_pattern,
      member_count: members.length,
      env_count: new Set(members.map(member => member.env_id)).size,
    };
    const old = ctx.db.rule.rule_id.find(rule_id);
    if (!old) ctx.db.rule.insert(row);
    else if (old.title !== row.title || old.defense_pattern !== row.defense_pattern
      || old.member_count !== row.member_count || old.env_count !== row.env_count) ctx.db.rule.rule_id.update(row);
  }
}

export const graph_on_invariant = spacetimedb.reducer(
  { invariant_id: t.string() },
  (ctx, { invariant_id }) => {
    requireWriter(ctx);
    if (!invariant_id.trim()) throw new SenderError('invariant_id must not be empty');
    recompute(ctx);
  },
);
export const rebuild_graph = spacetimedb.reducer(ctx => { requireWriter(ctx); recompute(ctx); });
export const set_graph_config = spacetimedb.reducer(
  { edge_threshold: t.f32(), max_edges_per_node: t.u32() },
  (ctx, { edge_threshold, max_edges_per_node }) => {
    requireWriter(ctx);
    if (!Number.isFinite(edge_threshold) || edge_threshold < 0 || edge_threshold > 1) {
      throw new SenderError('edge_threshold must be between 0 and 1');
    }
    if (!Number.isInteger(max_edges_per_node) || max_edges_per_node < 0 || max_edges_per_node > 0xffffffff) {
      throw new SenderError('max_edges_per_node must be a u32 integer');
    }
    ensureConfig(ctx);
    ctx.db.graph_config.id.update({ id: 0, edge_threshold, max_edges_per_node });
    recompute(ctx);
  },
);
export const set_rule_title = spacetimedb.reducer(
  { rule_id: t.string(), title: t.string() },
  (ctx, { rule_id, title }) => {
    requireWriter(ctx);
    if (!EXPLOIT_CLASSES.has(rule_id)) throw new SenderError('Unknown rule_id');
    const clean = title.trim();
    if (!clean || clean.length > 80) throw new SenderError('title must contain between 1 and 80 characters');
    ensureConfig(ctx);
    const row = { rule_id, title: clean };
    if (ctx.db.rule_title.rule_id.find(rule_id)) ctx.db.rule_title.rule_id.update(row);
    else ctx.db.rule_title.insert(row);
    recompute(ctx);
  },
);
