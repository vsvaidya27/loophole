/**
 * A small policy that learns to play the higher/lower game with REINFORCE. Each turn it picks
 * how many numbers to put in its reply and whether to use the game's hints (bisect) or guess at
 * random. It is not a language model: it shows, in seconds and in the browser, what the GPU runs
 * show for one. A policy paid by the shipped reward learns to list numbers; one paid by the
 * hardened reward learns to search.
 */
import { HIGH, LOW, MAX_TURNS, newGame, reward, step, type GameState, type Mode } from './higherLower';

export const LIST_SIZES = [1, 2, 4, 8, 16, 40] as const;
export interface Policy { listLogits: number[]; hintLogit: number }
export interface Turn { reply: string; message: string; listIndex: number; useHints: boolean }
export interface Episode { secret: number; turns: Turn[]; reward: number; realWin: boolean }

/** Deterministic random numbers (mulberry32), so a run replays identically. */
export function seeded(seed: number) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
type Random = () => number;
const int = (random: Random, lo: number, hi: number) => lo + Math.floor(random() * (hi - lo + 1));
const softmax = (logits: number[]) => {
  const top = Math.max(...logits), exps = logits.map(x => Math.exp(x - top)), sum = exps.reduce((a, b) => a + b, 0);
  return exps.map(x => x / sum);
};
const sigmoid = (x: number) => 1 / (1 + Math.exp(-x));
const logit = (p: number) => Math.log(p / (1 - p));

/** An untrained agent: mostly one guess per reply, mostly ignoring the hints. Tuned with the
 *  learning rate below so the hardened run passes 80% real wins around step 25 of 60. */
export const untrained = (): Policy => ({
  listLogits: [0.75, 0.05, 0.05, 0.05, 0.05, 0.05].map(Math.log),
  hintLogit: logit(0.1),
});

export const listProbabilities = (policy: Policy) => softmax(policy.listLogits);
export const hintProbability = (policy: Policy) => sigmoid(policy.hintLogit);

function bounds(state: GameState) {
  let lo = LOW, hi = HIGH;
  for (const h of state.history) {
    if (h.feedback === 'higher') lo = Math.max(lo, h.guess + 1);
    else if (h.feedback === 'lower') hi = Math.min(hi, h.guess - 1);
  }
  return lo <= hi ? [lo, hi] : [LOW, HIGH];
}

function compose(state: GameState, size: number, useHints: boolean, random: Random): string {
  const [lo, hi] = bounds(state);
  const first = useHints ? Math.floor((lo + hi) / 2) : int(random, LOW, HIGH);
  if (size === 1) return `<answer>${first}</answer>`;
  const pool = Array.from({ length: HIGH - LOW + 1 }, (_, i) => LOW + i).filter(n => n !== first);
  for (let i = pool.length - 1; i > 0; i--) { const j = int(random, 0, i); [pool[i], pool[j]] = [pool[j], pool[i]]; }
  const extra = pool.slice(0, size - 1).sort((a, b) => a - b);
  return `<answer>${first}</answer> or maybe ${extra.join(', ')}`;
}

/** Play one episode in `mode`; `realWin` replays the same replies under the game's exact rules. */
export function playEpisode(policy: Policy, mode: Mode, random: Random, secret = int(random, LOW, HIGH)): Episode {
  const state = newGame(secret), exact = newGame(secret);
  const turns: Turn[] = [];
  const sizes = listProbabilities(policy), hint = hintProbability(policy);
  let exactDone = false;
  for (let t = 0; t < MAX_TURNS; t++) {
    let r = random(), listIndex = 0;
    while (listIndex < sizes.length - 1 && r >= sizes[listIndex]) { r -= sizes[listIndex]; listIndex += 1; }
    const useHints = random() < hint;
    const reply = compose(state, LIST_SIZES[listIndex], useHints, random);
    const { message, done } = step(state, reply, mode);
    if (!exactDone) exactDone = step(exact, reply, 'exact').done;
    turns.push({ reply, message, listIndex, useHints });
    if (done) break;
  }
  return { secret, turns, reward: reward(state, mode), realWin: exact.found };
}

export interface StepStats { reward: number; realWin: number; numbersPerReply: number; sample: Episode }

/** One policy-gradient update from a batch of episodes; returns the updated policy and stats. */
export function trainStep(policy: Policy, mode: Mode, random: Random, batch = 24, lr = 1.5): { policy: Policy; stats: StepStats } {
  const episodes = Array.from({ length: batch }, () => playEpisode(policy, mode, random));
  const baseline = episodes.reduce((sum, e) => sum + e.reward, 0) / batch;
  const sizes = listProbabilities(policy), hint = hintProbability(policy);
  const listGrad = sizes.map(() => 0);
  let hintGrad = 0;
  for (const episode of episodes) {
    const advantage = episode.reward - baseline;
    if (advantage === 0) continue;
    for (const turn of episode.turns) {
      sizes.forEach((p, j) => { listGrad[j] += advantage * ((j === turn.listIndex ? 1 : 0) - p); });
      hintGrad += advantage * ((turn.useHints ? 1 : 0) - hint);
    }
  }
  const next: Policy = {
    listLogits: policy.listLogits.map((x, j) => x + lr * listGrad[j] / batch),
    hintLogit: policy.hintLogit + lr * hintGrad / batch,
  };
  const replies = episodes.flatMap(e => e.turns.map(t => t.reply));
  const numbers = replies.reduce((sum, reply) => sum + (reply.match(/\d+/g) ?? []).length, 0) / Math.max(1, replies.length);
  return {
    policy: next,
    stats: { reward: baseline, realWin: episodes.filter(e => e.realWin).length / batch, numbersPerReply: numbers, sample: episodes[0] },
  };
}

/** Real win rate under the exact rules, on fresh games. */
export function evaluate(policy: Policy, random: Random, games = 200): number {
  let wins = 0;
  for (let i = 0; i < games; i++) if (playEpisode(policy, 'exact', random).realWin) wins += 1;
  return wins / games;
}
