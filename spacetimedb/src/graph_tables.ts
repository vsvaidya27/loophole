import { table, t } from 'spacetimedb/server';

export const graph_config = table({ name: 'graph_config', public: true }, {
  id: t.u32().primaryKey(),
  edge_threshold: t.f32(),
  max_edges_per_node: t.u32(),
});
export const similarity_edge = table({ name: 'similarity_edge', public: true }, {
  edge_id: t.string().primaryKey(),
  a_id: t.string().index('btree'),
  b_id: t.string().index('btree'),
  score: t.f32(),
});
export const rule = table({ name: 'rule', public: true }, {
  rule_id: t.string().primaryKey(),
  title: t.string(),
  defense_pattern: t.string(),
  member_count: t.u32(),
  env_count: t.u32(),
});
export const rule_title = table({ name: 'rule_title', public: true }, {
  rule_id: t.string().primaryKey(),
  title: t.string(),
});
export const graphTables = { graph_config, similarity_edge, rule, rule_title };
