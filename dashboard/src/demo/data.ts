/** Shape of public/demo/loop-demo.json, written by scripts/build_loop_demo.py. */
export interface SourceLine { n: number; text: string; hot: boolean }
export interface Retrieved { id: string; env_id: string; exploit_class: string; title: string; defense: string; score: number; reasons: string[] }
export interface StoreInvariant { invariant_id: string; env_id: string; exploit_class: string; title: string; defense_pattern: string }
export interface SimilarityEdge { a_id: string; b_id: string; score: number }
export interface Attempt {
  id: string; class: string; plain: string; why_incorrect: string; secret: number; replies: string[];
  scores: { under_test: number; exact: number; shipped: number; hardened: number }; confirmed: boolean;
}
export interface Round { iteration: number; target: string; proposed: number; confirmed: number; patch_accepted: boolean; attempts: Attempt[] }

export interface DemoData {
  version: number;
  recorded: { run: string; date: string; auditor: string; status: string };
  store: { host: string; database: string };
  game: { env_id: string; name: string; description: string; max_turns: number; low: number; high: number; random_baseline: number; source: SourceLine[] };
  retrieval: { backend: string; model: string; indexed: number; query_ms?: number; offered_to_prompt: string[]; matches: Retrieved[] };
  graph_before: {
    environments: { env_id: string; source: string; title: string; status: string }[];
    invariants: StoreInvariant[];
    rules: { rule_id: string; title: string; member_count: number; env_count: number }[];
    similarity_edges: SimilarityEdge[];
  };
  rounds: Round[];
  patch: {
    summary: string; code: string;
    gates: { ok: boolean; reference: number; null: number; random: number; loopholes_closed: number; loopholes: number; legitimate_kept: number; legitimate: number };
  };
  learned: { invariants: StoreInvariant[]; similarity_edges: SimilarityEdge[] };
  calls: { count: number; cost_usd: number; model: string; seconds: number; by_role: Record<string, number> };
  gpu_evidence: { game: string; model: string; hardened: string; hackable: string; source: string };
}

export async function loadDemo(url = '/demo/loop-demo.json'): Promise<DemoData> {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`Could not load the demo data (${response.status}). Run scripts/build_loop_demo.py.`);
  return response.json() as Promise<DemoData>;
}

/** Plain names for the loophole families, for people who do not read reward code. */
export const FAMILY: Record<string, string> = {
  'multi-answer': 'Several answers at once',
  'parser-bypass': 'Odd formatting fools the parser',
  'lenient-normalization': 'Near-misses counted as right',
  'substring-match': 'Answer found anywhere in the text',
  'format-only': 'Right format, wrong answer',
  other: 'Other loopholes',
};
