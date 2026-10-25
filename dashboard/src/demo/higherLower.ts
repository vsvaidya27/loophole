/**
 * The higher/lower game (compiled/game_852c07fa.py) and its three rewards, ported for the
 * browser so the demo's agent learns on the real rules:
 *   shipped   the game as compiled: every number anywhere in a reply counts as a guess
 *   exact     the game's strict rules: one tagged guess per reply (the "real win")
 *   hardened  hardened/higher_lower_40.py: shipped plus the fixer's `tighten` rule
 * Parity with the Python game is checked against fixtures/higher_lower_parity.json.
 */
export type Mode = 'shipped' | 'exact' | 'hardened';
export const LOW = 1, HIGH = 40, MAX_TURNS = 7;

export interface GameState {
  secret: number; turns: number; found: boolean;
  history: { guess: number; feedback: 'higher' | 'lower' | 'correct' }[];
  replies: string[];
}

const NUM = /\d{1,3}/g;                              // Game.NUM, the loose candidate parser
const ANSWER = /<answer>([\s\S]*?)<\/answer>/gi;     // template.ANSWER_RE (dotall, ignore case)
const TAG_ANY = /<answer>[\s\S]*?<\/answer>/g;       // tighten's _TAG_ANY (dotall, case-sensitive)
const TAG = /^<answer>\s*(\d{1,3})\s*<\/answer>$/;   // tighten's _TAG, as a full match
const ANY_NUMBER = /\d+/g;

export const newGame = (secret: number): GameState => ({ secret, turns: 0, found: false, history: [], replies: [] });

function answers(reply: string, strict: boolean): string[] {
  if (!strict) return reply.match(NUM) ?? [];
  const tagged = [...reply.matchAll(ANSWER)].map(match => match[1]);
  return tagged.length ? [tagged[tagged.length - 1].trim()] : [];
}

function validGuesses(reply: string, strict: boolean): number[] {
  const out: number[] = [];
  for (const raw of answers(reply, strict)) {
    const text = raw.trim();
    if (/^\d{1,3}$/.test(text)) {
      const n = Number(text);
      if (n >= LOW && n <= HIGH) out.push(n);
    }
  }
  return strict ? out.slice(0, 1) : out;
}

/** One turn. Returns the game's reply and whether the episode is over. */
export function step(state: GameState, reply: string, mode: Mode): { message: string; done: boolean } {
  state.turns += 1;
  state.replies.push(reply);
  const valid = validGuesses(reply ?? '', mode === 'exact');
  let message = `No valid guess found. Reply with one number from ${LOW} to ${HIGH}, like <answer>20</answer>.`;
  if (valid.length) {
    if (valid.includes(state.secret)) state.found = true;
    const first = valid[0];
    const feedback = state.found ? 'correct' : first < state.secret ? 'higher' : 'lower';
    state.history.push({ guess: first, feedback });
    message = state.found ? 'Correct!' : `${feedback[0].toUpperCase()}${feedback.slice(1)}.`;
  }
  const done = state.found || state.turns >= MAX_TURNS;
  if (done && !state.found) message += ` Out of guesses; the number was ${state.secret}.`;
  return { message, done };
}

/** tighten's per-reply check: exactly one number in the reply, inside exactly one answer tag. */
export function replyOk(reply: string): boolean {
  const text = reply ?? '';
  if ((text.match(ANY_NUMBER) ?? []).length !== 1) return false;
  const tags = text.match(TAG_ANY) ?? [];
  if (tags.length !== 1) return false;
  const match = TAG.exec(tags[0]);
  if (!match) return false;
  const n = Number(match[1]);
  return n >= LOW && n <= HIGH;
}

export function reward(state: GameState, mode: Mode): number {
  const base = state.found ? 1 : 0;
  if (mode !== 'hardened' || base <= 0) return base;
  return state.replies.every(replyOk) ? base : 0;
}

/** Replay fixed replies, stopping when the game ends (as the Python auditor does). */
export function playReplies(secret: number, replies: string[], mode: Mode) {
  const state = newGame(secret);
  let used = 0;
  for (const reply of replies) {
    used += 1;
    if (step(state, reply, mode).done) break;
  }
  return { reward: reward(state, mode), used };
}
