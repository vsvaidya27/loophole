export const humanize = (value: string) => value.replaceAll('_', ' ').replaceAll('-', ' ');

export const score = (value: number | undefined) =>
  typeof value === 'number' && Number.isFinite(value)
    ? value.toLocaleString(undefined, { maximumFractionDigits: 3 })
    : 'Not recorded';

export function provenance(env?: { envId: string; source: string; title?: string }) {
  if (!env) return 'Source pending';
  if (env.envId.includes('/scripted-')) return 'Scripted calibration';
  if (env.envId.includes('/ai-') || env.title?.includes('model-generated')) return 'Model-generated pilot';
  return humanize(env.source);
}
