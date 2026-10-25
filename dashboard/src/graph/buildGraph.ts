export type GraphOutcome = 'pre_hardened' | 'blocked' | 'not_blocked' | 'not_applicable';
export type GraphNode =
  | { id: `env:${string}`; kind: 'environment'; label: string; source: string; status: string }
  | { id: `inv:${string}`; kind: 'invariant'; label: string; exploitClass: string; envId: string; pending: boolean }
  | { id: `rule:${string}`; kind: 'rule'; label: string; memberCount: number; envCount: number };
export type GraphEdge = {
  id: string; kind: 'found_in' | 'instance_of' | 'similar_to' | 'applied_to';
  source: string; target: string; weight?: number; outcome?: GraphOutcome;
};
export type GraphDiagnostic = { table: string; rowId: string; message: string };
export interface EnvironmentRow { envId: string; source: string; title: string; status: string }
export interface InvariantRow { invariantId: string; envId: string; exploitClass: string; title: string }
export interface ExploitRow { invariantId: string; envId: string; exploitClass: string; summary: string }
export interface RuleRow { ruleId: string; title: string; memberCount: number; envCount: number }
export interface SimilarityEdgeRow { edgeId: string; aId: string; bId: string; score: number }
export interface RuleApplicationRow {
  applicationKey: string; invariantId: string; targetEnvId: string; outcome: string;
  createdAt: { microsSinceUnixEpoch: bigint } | string;
}
export interface GraphRows {
  environments: readonly EnvironmentRow[]; exploits: readonly ExploitRow[];
  invariants: readonly InvariantRow[]; rules: readonly RuleRow[];
  similarityEdges: readonly SimilarityEdgeRow[]; ruleApplications: readonly RuleApplicationRow[];
}
export interface GraphProjection { nodes: GraphNode[]; edges: GraphEdge[]; diagnostics: GraphDiagnostic[] }
const outcomes = new Set(['pre_hardened', 'blocked', 'not_blocked', 'not_applicable']);
function compare(a: string, b: string): number { return a < b ? -1 : a > b ? 1 : 0; }
function time(row: RuleApplicationRow): bigint | undefined {
  if (typeof row.createdAt === 'object' && row.createdAt !== null) return row.createdAt.microsSinceUnixEpoch;
  if (typeof row.createdAt !== 'string') return undefined;
  if (/^-?\d+$/.test(row.createdAt)) return BigInt(row.createdAt);
  const ms = Date.parse(row.createdAt);
  return Number.isFinite(ms) ? BigInt(ms) * 1000n : undefined;
}

/** Pure projection of generated client rows. Incomplete subscriptions never invent edges. */
export function buildGraph(rows: GraphRows, opts: { hideSeed?: boolean } = {}): GraphProjection {
  const nodes = new Map<string, GraphNode>();
  const edges = new Map<string, GraphEdge>();
  const diagnostics: GraphDiagnostic[] = [];
  const warn = (table: string, rowId: string, message: string) => diagnostics.push({ table, rowId, message });
  const hidden = new Set(rows.environments.filter(row => opts.hideSeed && row.source === 'seed').map(row => row.envId));
  const invariants = new Map(rows.invariants.filter(row => !hidden.has(row.envId)).map(row => [row.invariantId, row]));
  for (const row of rows.environments) {
    if (!hidden.has(row.envId)) nodes.set(`env:${row.envId}`, {
      id: `env:${row.envId}`, kind: 'environment', label: row.title || row.envId, source: row.source, status: row.status,
    });
  }
  for (const row of rows.exploits) {
    if (!hidden.has(row.envId) && !invariants.has(row.invariantId)) nodes.set(`inv:${row.invariantId}`, {
      id: `inv:${row.invariantId}`, kind: 'invariant', label: row.summary || row.invariantId,
      exploitClass: row.exploitClass, envId: row.envId, pending: true,
    });
  }
  for (const row of invariants.values()) nodes.set(`inv:${row.invariantId}`, {
    id: `inv:${row.invariantId}`, kind: 'invariant', label: row.title || row.invariantId,
    exploitClass: row.exploitClass, envId: row.envId, pending: false,
  });
  for (const row of rows.rules) {
    const members = [...invariants.values()].filter(inv => inv.exploitClass === row.ruleId);
    if (opts.hideSeed && members.length === 0) continue;
    nodes.set(`rule:${row.ruleId}`, {
      id: `rule:${row.ruleId}`, kind: 'rule', label: row.title || row.ruleId,
      memberCount: opts.hideSeed ? members.length : row.memberCount,
      envCount: opts.hideSeed ? new Set(members.map(inv => inv.envId)).size : row.envCount,
    });
  }
  const addEdge = (edge: GraphEdge, table: string, rowId: string) => {
    if (!nodes.has(edge.source) || !nodes.has(edge.target)) {
      warn(table, rowId, 'endpoint node has not arrived');
      return;
    }
    edges.set(edge.id, edge);
  };
  for (const node of nodes.values()) {
    if (node.kind !== 'invariant') continue;
    const invariantId = node.id.slice(4);
    addEdge({ id: `found_in:${invariantId}`, kind: 'found_in', source: node.id, target: `env:${node.envId}` }, 'invariant', invariantId);
    if (!node.pending) addEdge({ id: `instance_of:${invariantId}`, kind: 'instance_of', source: node.id, target: `rule:${node.exploitClass}` }, 'invariant', invariantId);
  }
  for (const row of rows.similarityEdges) {
    const left = rows.invariants.find(inv => inv.invariantId === row.aId);
    const right = rows.invariants.find(inv => inv.invariantId === row.bId);
    if ((left && hidden.has(left.envId)) || (right && hidden.has(right.envId))) continue;
    if (row.aId === row.bId || !Number.isFinite(row.score) || row.score < 0 || row.score > 1) {
      warn('similarity_edge', row.edgeId, 'self edge or invalid score');
      continue;
    }
    if (!invariants.has(row.aId) || !invariants.has(row.bId)) {
      warn('similarity_edge', row.edgeId, 'invariant endpoint has not arrived');
      continue;
    }
    const [a, b] = [row.aId, row.bId].sort(compare);
    const id = `similar_to:${a}|${b}`;
    if ((edges.get(id)?.weight ?? -1) >= row.score) continue;
    addEdge({ id, kind: 'similar_to', source: `inv:${a}`, target: `inv:${b}`, weight: row.score }, 'similarity_edge', row.edgeId);
  }
  const latest = new Map<string, { row: RuleApplicationRow; at: bigint }>();
  for (const row of rows.ruleApplications) {
    const at = time(row);
    if (at === undefined) { warn('rule_application', row.applicationKey, 'invalid createdAt'); continue; }
    const key = JSON.stringify([row.invariantId, row.targetEnvId]);
    const prior = latest.get(key);
    if (!prior || at > prior.at || (at === prior.at && row.applicationKey > prior.row.applicationKey)) latest.set(key, { row, at });
  }
  for (const { row } of latest.values()) {
    const sourceRow = rows.invariants.find(inv => inv.invariantId === row.invariantId);
    if (hidden.has(row.targetEnvId) || (sourceRow && hidden.has(sourceRow.envId))) continue;
    const inv = invariants.get(row.invariantId);
    if (!inv) { warn('rule_application', row.applicationKey, 'source invariant has not arrived'); continue; }
    if (inv.envId === row.targetEnvId) { warn('rule_application', row.applicationKey, 'source-environment application is not transfer'); continue; }
    if (!outcomes.has(row.outcome)) { warn('rule_application', row.applicationKey, 'unknown outcome'); continue; }
    addEdge({ id: `applied_to:${row.invariantId}->${row.targetEnvId}`, kind: 'applied_to',
      source: `rule:${inv.exploitClass}`, target: `env:${row.targetEnvId}`, outcome: row.outcome as GraphOutcome,
    }, 'rule_application', row.applicationKey);
  }
  return {
    nodes: [...nodes.values()].sort((a, b) => compare(a.id, b.id)),
    edges: [...edges.values()].sort((a, b) => compare(a.id, b.id)),
    diagnostics: diagnostics.sort((a, b) => compare(JSON.stringify(a), JSON.stringify(b))),
  };
}
