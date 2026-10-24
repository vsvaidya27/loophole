// Core reducers (Varun). The Python pusher calls these over HTTP with positional JSON
// arguments in the declared order. Every write is an idempotent upsert, so any call can be
// retried after a 504 / "outcome unknown". index.ts re-exports this file, so it exports
// ONLY reducers; helpers stay unexported.
import { t, SenderError } from 'spacetimedb/server';
import spacetimedb, { type Ctx } from './schema';
import { EXPLOIT_CLASSES } from './taxonomy';

const SOURCES = new Set(['hub', 'game', 'seed']);
const ENV_STATUSES = new Set([
  'queued', 'running', 'patched', 'robust', 'failed_to_run',
  'compiling', 'pre_hardening', 'hardening', 'training', 'done',
]);
const OUTCOMES = new Set(['pre_hardened', 'blocked', 'not_blocked', 'not_applicable']);
const DETAIL_VERSION = 1;
const EMBEDDING_DIM = 384;
const MIN_TEXT = 10;
const MAX_TITLE = 80;
const MAX_SAMPLE = 2000;

function oneOf(field: string, value: string, allowed: ReadonlySet<string>) {
  if (!allowed.has(value)) {
    throw new SenderError(`${field} must be one of ${[...allowed].join(', ')}; got '${value}'`);
  }
}

function nonEmpty(field: string, value: string) {
  if (!value.trim()) throw new SenderError(`${field} must not be empty`);
}

function requireEnvironment(ctx: Ctx, env_id: string) {
  if (!ctx.db.environment.env_id.find(env_id)) {
    throw new SenderError(`record_environment must be called before writing to ${env_id}`);
  }
}

function checkEmbedding(vector: number[]) {
  if (vector.length === 0) return;
  if (vector.length !== EMBEDDING_DIM || !vector.every(Number.isFinite)) {
    throw new SenderError(`embedding must be empty or ${EMBEDDING_DIM} finite values, got ${vector.length}`);
  }
  const norm = Math.sqrt(vector.reduce((sum, x) => sum + x * x, 0));
  if (Math.abs(norm - 1) >= 1e-3) throw new SenderError(`embedding must be L2-normalized, norm is ${norm}`);
}

function checkDetail(detail: string) {
  let parsed: unknown;
  try {
    parsed = JSON.parse(detail);
  } catch {
    throw new SenderError('detail must be JSON');
  }
  const version = (parsed as { v?: unknown } | null)?.v;
  if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed) || version !== DETAIL_VERSION) {
    throw new SenderError(`detail must be a JSON object with "v": ${DETAIL_VERSION}`);
  }
}

const invariantIdOf = (env_id: string, exploit_id: string) => `${env_id}#${exploit_id}`;

export const record_environment = spacetimedb.reducer(
  { env_id: t.string(), source: t.string(), title: t.string(), status: t.string() },
  (ctx, { env_id, source, title, status }) => {
    nonEmpty('env_id', env_id);
    oneOf('source', source, SOURCES);
    oneOf('status', status, ENV_STATUSES);
    const row = { env_id, source, title, status, updated_at: ctx.timestamp };
    if (ctx.db.environment.env_id.find(env_id)) ctx.db.environment.env_id.update(row);
    else ctx.db.environment.insert(row);
  }
);

export const record_exploit = spacetimedb.reducer(
  {
    env_id: t.string(),
    exploit_id: t.string(),
    exploit_class: t.string(),
    iteration: t.u32(),
    summary: t.string(),
    sample_completion: t.string(),
    reward_original: t.f32(),
    evidence_path: t.string(),
  },
  (ctx, args) => {
    requireEnvironment(ctx, args.env_id);
    nonEmpty('exploit_id', args.exploit_id);
    oneOf('exploit_class', args.exploit_class, EXPLOIT_CLASSES);
    if (!Number.isInteger(args.iteration) || args.iteration < 1 || args.iteration > 5) {
      throw new SenderError(`iteration must be 1..5, got ${args.iteration}`);
    }
    if (!Number.isFinite(args.reward_original)) throw new SenderError('reward_original must be finite');
    const invariant_id = invariantIdOf(args.env_id, args.exploit_id);
    const existing = ctx.db.exploit.invariant_id.find(invariant_id);
    const row = {
      invariant_id,
      env_id: args.env_id,
      exploit_id: args.exploit_id,
      exploit_class: args.exploit_class,
      iteration: args.iteration,
      summary: args.summary,
      sample_completion: args.sample_completion.slice(0, MAX_SAMPLE),
      reward_original: args.reward_original,
      // A retry or a sync replay must not un-patch the exploit.
      reward_patched: existing?.reward_patched,
      status: existing?.status ?? 'confirmed',
      evidence_path: args.evidence_path,
      confirmed_at: existing?.confirmed_at ?? ctx.timestamp,
    };
    if (existing) ctx.db.exploit.invariant_id.update(row);
    else ctx.db.exploit.insert(row);
  }
);

export const mark_exploit_patched = spacetimedb.reducer(
  { env_id: t.string(), exploit_id: t.string(), reward_patched: t.f32() },
  (ctx, { env_id, exploit_id, reward_patched }) => {
    const invariant_id = invariantIdOf(env_id, exploit_id);
    const existing = ctx.db.exploit.invariant_id.find(invariant_id);
    if (!existing) throw new SenderError(`no exploit ${invariant_id}`);
    if (!Number.isFinite(reward_patched)) throw new SenderError('reward_patched must be finite');
    ctx.db.exploit.invariant_id.update({ ...existing, reward_patched, status: 'patched' });
  }
);

export const record_invariant = spacetimedb.reducer(
  {
    env_id: t.string(),
    exploit_id: t.string(),
    title: t.string(),
    mechanism: t.string(),
    root_cause: t.string(),
    preconditions: t.string(),
    defense_pattern: t.string(),
    evidence_path: t.string(),
    embedding_model: t.string(),
    embedding: t.array(t.f32()),
  },
  (ctx, args) => {
    const invariant_id = invariantIdOf(args.env_id, args.exploit_id);
    const source = ctx.db.exploit.invariant_id.find(invariant_id);
    if (!source) throw new SenderError(`record_exploit must be called before record_invariant (${invariant_id})`);
    nonEmpty('title', args.title);
    for (const field of ['mechanism', 'root_cause', 'preconditions', 'defense_pattern'] as const) {
      if (args[field].trim().length < MIN_TEXT) {
        throw new SenderError(`${field} must be at least ${MIN_TEXT} characters`);
      }
    }
    checkEmbedding(args.embedding);

    const existing = ctx.db.invariant.invariant_id.find(invariant_id);
    const row = {
      invariant_id,
      env_id: args.env_id,
      exploit_id: args.exploit_id,
      exploit_class: source.exploit_class,
      title: args.title.slice(0, MAX_TITLE),
      mechanism: args.mechanism,
      root_cause: args.root_cause,
      preconditions: args.preconditions,
      defense_pattern: args.defense_pattern,
      evidence_path: args.evidence_path,
      created_at: existing?.created_at ?? ctx.timestamp,
    };
    if (existing) ctx.db.invariant.invariant_id.update(row);
    else ctx.db.invariant.insert(row);

    const embedding = { invariant_id, model: args.embedding_model, vector: args.embedding };
    if (ctx.db.invariant_embedding.invariant_id.find(invariant_id)) {
      ctx.db.invariant_embedding.invariant_id.update(embedding);
    } else {
      ctx.db.invariant_embedding.insert(embedding);
    }
  }
);

export const record_rule_application = spacetimedb.reducer(
  {
    run_id: t.string(),
    invariant_id: t.string(),
    target_env_id: t.string(),
    outcome: t.string(),
    detail: t.string(),
  },
  (ctx, { run_id, invariant_id, target_env_id, outcome, detail }) => {
    nonEmpty('run_id', run_id);
    oneOf('outcome', outcome, OUTCOMES);
    checkDetail(detail);
    if (!ctx.db.invariant.invariant_id.find(invariant_id)) throw new SenderError(`no invariant ${invariant_id}`);
    requireEnvironment(ctx, target_env_id);
    const application_key = `${run_id}:${invariant_id}->${target_env_id}`;
    const existing = ctx.db.rule_application.application_key.find(application_key);
    const row = {
      application_key,
      run_id,
      invariant_id,
      target_env_id,
      outcome,
      detail,
      created_at: existing?.created_at ?? ctx.timestamp,
    };
    if (existing) ctx.db.rule_application.application_key.update(row);
    else ctx.db.rule_application.insert(row);
  }
);

export const clear_environment = spacetimedb.reducer(
  { env_id: t.string() },
  (ctx, { env_id }) => {
    // The environment row stays; the caller follows up with rebuild_graph.
    for (const row of [...ctx.db.invariant.env_id.filter(env_id)]) {
      ctx.db.invariant_embedding.invariant_id.delete(row.invariant_id);
      ctx.db.rule_application.invariant_id.delete(row.invariant_id);
    }
    ctx.db.invariant.env_id.delete(env_id);
    ctx.db.exploit.env_id.delete(env_id);
    ctx.db.rule_application.target_env_id.delete(env_id);
  }
);
