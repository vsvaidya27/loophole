import catalog from './catalog.json';

export type Policy = 'base' | 'hacked' | 'hardened';
export const policies: Policy[] = ['base', 'hacked', 'hardened'];
export const policyNames: Record<Policy, string> = { base: 'Base policy', hacked: 'Reward hacked', hardened: 'Hardened' };
export const percent = (value: number) => `${Math.round(value * 100)}%`;
export type Scores = { strict: number; loose: number };
export type VoiceSummary = { asr_before: number; asr_after: number; benign_before: number; benign_after: number };
export type Demo = {
  id: string; title: string; game: string; hook: string; loophole: string; description: string;
  placeholder: boolean; kind: string; samples: number; source: string; video: string; data: string;
  scores: Partial<Record<Policy, Scores>>; summary: VoiceSummary | null;
};
export const demos = catalog.demos as Demo[];
export const sourceRevision = catalog.revision;
export type Rollout = Scores & {
  answer?: string; completion?: string; best_loose?: string;
  pages?: string[]; loose_pages?: string[]; transcript?: [string, string][];
  loose_transcript?: [string, string][]; turns?: number; n_words: number;
};
export type Task = {
  question: string; reference?: string;
  info?: { prices?: number[]; future?: number; [key: string]: unknown };
  rollouts: Record<Policy, Rollout>;
};
export type GameData = { game: string; placeholder: boolean; kind?: 'single' | 'multi'; tasks: Task[] };
export type Verdict = { success: boolean; reason: string };
export type VoiceCall = {
  id: string; label: string; honest: boolean; correct_action: string; decision: string;
  true_success: boolean; transcript: [string, string][]; audio?: string[];
  verdicts: { baseline: Verdict; hardened: Verdict };
};
export type VoiceData = {
  game: string; kind: 'voice'; placeholder: false; description: string; provenance: string; summary: VoiceSummary;
  judges: { baseline: string; hardened: string }; calls: VoiceCall[];
};
export type DemoData = GameData | VoiceData;

/** Match the upstream showcase ranking while retaining the original example numbers. */
export function featuredTask(tasks: Task[]) {
  const rank = (task: Task) => {
    const { hacked, hardened, base } = task.rollouts;
    const hack = hacked.loose - hacked.strict > 0.01;
    return Number(!(hack && hardened.strict >= 1)) * 4 + Number(base.strict >= 1) * 2 + Number(!hack);
  };
  return tasks.reduce((best, task, index) => rank(task) < rank(tasks[best]) ? index : best, 0);
}

export type RewardMode = 'strict' | 'loose';
export function replayRow(row: Rollout, mode: RewardMode) {
  return mode === 'loose' ? { ...row, pages: row.loose_pages ?? row.pages, transcript: row.loose_transcript ?? row.transcript } : row;
}

export function replayLength(task: Task, mode: RewardMode = 'strict') {
  return Math.max(task.info?.prices ? 3 : 1, ...policies.map(policy =>
    (replayRow(task.rollouts[policy], mode).pages?.length || 1) - 1));
}

export const evidenceLabel = (demo: Demo) => demo.placeholder ? 'Scripted example' : demo.kind === 'voice' ? 'Recorded audit' : 'Recorded training run';

export function policyCaption(placeholder: boolean, policy: Policy) {
  return placeholder
    ? { base: 'Random policy', hacked: 'Scripted exploit', hardened: 'Reference solver' }[policy]
    : { base: 'Before RL training', hacked: 'Trained on loose reward', hardened: 'Trained on fixed reward' }[policy];
}
