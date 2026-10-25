// Build a browser-safe, reproducible projection of the committed audit evidence.
// No model calls, database writes, or credentials. Never exports API-call logs.
import { readFileSync, writeFileSync, mkdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { resolve, dirname, relative } from 'node:path';
import { createHash } from 'node:crypto';
import { execFileSync } from 'node:child_process';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '../..');
const read = path => {
  const full = resolve(root, path);
  if (relative(root, full).startsWith('..')) throw new Error('Evidence path escapes repository');
  return readFileSync(full, 'utf8');
};
const json = path => JSON.parse(read(path));
const lines = path => read(path).split('\n').filter(line => line.trim()).map(line => JSON.parse(line));
const requireValue = (ok, message) => { if (!ok) throw new Error(message); };
const boardText = read('results/leaderboard.json');
const board = JSON.parse(boardText);
const batch = json('results/invariant_graph_batch.json');
const manifest = json('results/audit_batch/final_manifest.json');
const records = new Map(batch.entries.map(row => [`${row.env_id}#${row.exploit.exploit_id}`, row]));
const statusLabels = { patched: 'Repaired', unpatched: 'Open findings', robust: 'No findings in probes', failed_to_run: 'Could not run' };

const entries = board.entries.map(entry => {
  requireValue(entry.status in statusLabels, `Unknown outcome for ${entry.env_id}`);
  for (const field of ['asr_before', 'asr_after', 'benign_pass_before', 'benign_pass_after']) {
    const value = entry[field];
    requireValue(entry.status === 'failed_to_run' ? value === null : Number.isFinite(value) && value >= 0 && value <= 1,
                 `Invalid ${field} for ${entry.env_id}`);
  }
  const failed = entry.status === 'failed_to_run';
  const summary = failed ? null : json(`${entry.evidence_dir}/summary.json`);
  const attempts = failed ? [] : lines(`${entry.evidence_dir}/attempts.jsonl`);
  const benign = failed ? [] : lines(`${entry.evidence_dir}/benign.jsonl`);
  const findings = entry.exploits.map(exploit => {
    const id = `${entry.env_id}#${exploit.exploit_id}`;
    const record = records.get(id);
    requireValue(record, `Missing export record ${id}`);
    const evidencePath = `${entry.evidence_dir}/${exploit.replay}`;
    requireValue(record.invariant.evidence_path === evidencePath, `Evidence mismatch ${id}`);
    const replay = json(evidencePath);
    requireValue(replay.env_id === entry.env_id && replay.exploit_id === exploit.exploit_id && replay.cases.length > 0,
                 `Invalid replay ${id}`);
    const sample = replay.cases[0];
    const patched = record.exploit.reward_patched ?? null;
    return { id, exploitId: exploit.exploit_id, title: record.invariant.title, exploitClass: exploit.exploit_class,
      mechanism: record.invariant.mechanism, preconditions: record.invariant.preconditions,
      defense: record.invariant.defense_pattern, evidencePath, closed: patched !== null,
      originalReward: record.exploit.reward_original, patchedReward: patched,
      submittedAnswer: sample.completion, referenceAnswer: sample.reference_completion,
      verdict: sample.judge?.verdict ?? 'not recorded', verdictReason: sample.judge?.reason ?? '',
    };
  });
  return { envId: entry.env_id, name: entry.env_id.split('/').slice(1).join('/'), publisher: entry.env_id.split('/')[0],
    status: entry.status, asrBefore: entry.asr_before, asrAfter: entry.asr_after,
    benignBefore: entry.benign_pass_before, benignAfter: entry.benign_pass_after,
    rounds: entry.iterations, costUsd: entry.cost_usd, evidenceDir: entry.evidence_dir,
    failureReason: failed ? entry.failure_reason : null,
    unpatchedReasons: summary?.unpatched_because ?? [], stopReason: summary?.stop_reason ?? null,
    probes: attempts.length,
    benignCases: new Set(benign.map(row => JSON.stringify([row.example_index, row.completion]))).size,
    findings, closed: findings.filter(f => f.closed).length, open: findings.filter(f => !f.closed).length,
    classes: [...new Set(findings.map(f => f.exploitClass))].sort(),
  };
});
const findings = entries.flatMap(row => row.findings);
requireValue(entries.length === manifest.leaderboard_entries && findings.length === manifest.invariants, 'Manifest totals mismatch');
requireValue(findings.filter(row => row.closed).length === manifest.closed_exploits, 'Closed finding total mismatch');
requireValue(new Set(findings.map(f => f.id)).size === findings.length, 'Duplicate finding IDs');
const dataset = {
  version: 1, auditDate: '2026-10-24',
  source: { path: 'results/leaderboard.json', sha256: createHash('sha256').update(boardText).digest('hex'),
    commit: execFileSync('git', ['log', '-1', '--format=%H', '--', 'results/audit_batch/final_manifest.json'], { cwd: root, encoding: 'utf8' }).trim(),
    checkerPassed: manifest.checker.passed, checkerLog: manifest.checker.log,
    protocol: 'At most five rounds of three probes, with independent correctness checks and benign-answer repair gates.',
  }, entries,
};
const output = resolve(root, 'dashboard/src/data/hubLeaderboard.json');
mkdirSync(dirname(output), { recursive: true });
writeFileSync(output, JSON.stringify(dataset, null, 2) + '\n');
console.log(`Exported ${entries.length} Hub environments, ${findings.length} findings, ${findings.filter(f => f.closed).length} closed.`);
