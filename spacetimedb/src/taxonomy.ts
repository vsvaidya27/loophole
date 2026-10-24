// Exploit classes. Keep in sync with harden/store/exploit_classes.json (a test checks it).
// Not re-exported by index.ts: only reducers may reach the module root.
export const EXPLOIT_CLASSES: ReadonlySet<string> = new Set([
  'substring-match',
  'multi-answer',
  'format-only',
  'parser-bypass',
  'lenient-normalization',
  'constraint-gaming',
  'answer-leak',
  'judge-manipulation',
  'other',
]);
