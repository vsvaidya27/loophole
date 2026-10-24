// Core tables (Varun). See docs/INVARIANT_STORE.md for the contract.
// Columns cannot be renamed, retyped or reordered without wiping the database;
// new columns go at the end with .default(...).
import { table, t } from 'spacetimedb/server';

export const environment = table({ name: 'environment', public: true }, {
  env_id: t.string().primaryKey(),        // leaderboard env_id ("owner/name"), "game/<slug>" or "seed/<name>"
  source: t.string(),                     // 'hub' | 'game' | 'seed'
  title: t.string(),
  status: t.string(),                     // hub: queued|running|patched|robust|failed_to_run
                                          // game: compiling|pre_hardening|hardening|training|done
  updated_at: t.timestamp(),
});

export const exploit = table({ name: 'exploit', public: true }, {
  invariant_id: t.string().primaryKey(),  // `${env_id}#${exploit_id}`, shared with invariant
  env_id: t.string().index('btree'),
  exploit_id: t.string(),                 // same id as results/leaderboard.json
  exploit_class: t.string(),              // chosen once, here (taxonomy.ts)
  iteration: t.u32(),                     // 1..5
  summary: t.string(),                    // one line for the dashboard
  sample_completion: t.string(),          // the hack itself, truncated to 2000 chars
  reward_original: t.f32(),               // reward the hack earned before the patch
  reward_patched: t.option(t.f32()),      // set by mark_exploit_patched
  status: t.string(),                     // 'confirmed' | 'patched'
  evidence_path: t.string(),              // repo-relative replay file
  confirmed_at: t.timestamp(),
});

export const invariant = table({ name: 'invariant', public: true }, {
  invariant_id: t.string().primaryKey(),
  env_id: t.string().index('btree'),
  exploit_id: t.string(),
  exploit_class: t.string().index('btree'),  // copied from the exploit row
  title: t.string(),                      // <= 80 chars, node label
  mechanism: t.string(),                  // how the hack works
  root_cause: t.string(),                 // why the reward allowed it
  preconditions: t.string(),              // when the rule applies to another environment
  defense_pattern: t.string(),            // how to block it
  evidence_path: t.string(),
  created_at: t.timestamp(),              // kept on re-record; defines graph order
});

// Private: only module code reads vectors, so dashboard clients never download them.
export const invariant_embedding = table({ name: 'invariant_embedding' }, {
  invariant_id: t.string().primaryKey(),
  model: t.string(),                      // 'all-MiniLM-L6-v2', or '' if none
  vector: t.array(t.f32()),               // 384 floats L2-normalized, or empty
});

export const rule_application = table({ name: 'rule_application', public: true }, {
  application_key: t.string().primaryKey(),  // `${run_id}:${invariant_id}->${target_env_id}`, so retries upsert
  run_id: t.string().index('btree'),      // one transfer-test attempt; a new attempt gets a new run_id
  invariant_id: t.string().index('btree'),
  target_env_id: t.string().index('btree'),
  outcome: t.string(),                    // 'pre_hardened' | 'blocked' | 'not_blocked' | 'not_applicable'
  detail: t.string(),                     // versioned JSON, {"v": 1, ...}; see the doc's Transfer test
  created_at: t.timestamp(),              // kept on retry
});

export const coreTables = { environment, exploit, invariant, invariant_embedding, rule_application };
