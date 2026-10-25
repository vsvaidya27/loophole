import data from './data/hubLeaderboard.json';

export type AuditStatus = 'patched' | 'unpatched' | 'robust' | 'failed_to_run';
export type Finding = {
  id: string; exploitId: string; title: string; exploitClass: string; mechanism: string;
  preconditions: string; defense: string; evidencePath: string; closed: boolean;
  originalReward: number; patchedReward: number | null; submittedAnswer: string;
  referenceAnswer: string; verdict: string; verdictReason: string;
};
export type AuditEntry = {
  envId: string; name: string; publisher: string; status: AuditStatus;
  asrBefore: number | null; asrAfter: number | null; benignBefore: number | null; benignAfter: number | null;
  rounds: number; costUsd: number; evidenceDir: string; failureReason: string | null;
  unpatchedReasons: string[]; stopReason: string | null; probes: number; benignCases: number;
  findings: Finding[]; closed: number; open: number; classes: string[];
};
export type AuditDataset = {
  version: number; auditDate: string;
  source: { path: string; sha256: string; commit: string; checkerPassed: boolean; checkerLog: string; protocol: string };
  entries: AuditEntry[];
};
export const leaderboard = data as AuditDataset;
export const statusLabels: Record<AuditStatus, string> = {
  patched: 'Repaired', unpatched: 'Open findings', robust: 'No findings in probes', failed_to_run: 'Could not run',
};
export const percent = (value: number | null) => value === null ? '—' : `${(value * 100).toLocaleString(undefined, { maximumFractionDigits: 1 })}%`;
export const evidenceUrl = (path: string) => `https://github.com/vsvaidya27/loophole/blob/${leaderboard.source.commit}/${path.split('/').map(encodeURIComponent).join('/')}`;

export function summarize(entries: AuditEntry[]) {
  return {
    environments: entries.length, loaded: entries.filter(e => e.status !== 'failed_to_run').length,
    repaired: entries.filter(e => e.status === 'patched').length,
    findings: entries.reduce((sum, e) => sum + e.findings.length, 0),
    closed: entries.reduce((sum, e) => sum + e.closed, 0), open: entries.reduce((sum, e) => sum + e.open, 0),
    probes: entries.reduce((sum, e) => sum + e.probes, 0),
  };
}

export type SortOrder = 'closed' | 'findings' | 'asr' | 'name';
export function sortEntries(entries: AuditEntry[], order: SortOrder) {
  return [...entries].sort((a, b) => {
    // Unavailable measurements are always last, never interpreted as zero risk.
    const available = Number(a.status === 'failed_to_run') - Number(b.status === 'failed_to_run');
    if (available) return available;
    if (order === 'name') return a.envId.localeCompare(b.envId);
    const delta = order === 'closed' ? b.closed - a.closed : order === 'findings' ? b.findings.length - a.findings.length
      : ((b.asrBefore ?? 0) - (b.asrAfter ?? 0)) - ((a.asrBefore ?? 0) - (a.asrAfter ?? 0));
    return delta || b.findings.length - a.findings.length || a.envId.localeCompare(b.envId);
  });
}
