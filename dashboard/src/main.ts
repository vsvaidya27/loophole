import './style.css';
import { renderGraph } from './graph/renderGraph';
import { connectLive, buildGraph, DEFAULT_DATABASE, DEFAULT_HOST, type LiveSnapshot } from './live';

const app = document.querySelector<HTMLDivElement>('#app')!;
app.innerHTML = `<main>
<header class="page-header"><div><a class="wordmark" href="/" aria-label="Loophole home"><span aria-hidden="true">∞</span> loophole</a><h1>Reward integrity</h1></div><nav aria-label="Main navigation"><a aria-current="page" href="/">Live audits</a><a href="/replay.html">Game & training replays <span aria-hidden="true">↗</span></a></nav></header>
<section class="connection" aria-label="Live connection"><div><span id="light"></span><strong id="status" role="status">Connecting</strong><span id="updated"></span></div><button id="retry">Reconnect</button><details class="connection-details"><summary>Connection details</summary><p id="endpoint"></p></details><p id="error" role="alert"></p></section>
<section class="metrics" id="metrics" aria-label="Knowledge store totals" aria-live="polite"></section>
<section class="workspace"><div class="graph-panel"><div class="toolbar"><div><div class="eyebrow">ENVIRONMENTS / FAILURES / CONSTRAINTS</div><h2>The invariant network</h2></div><div class="graph-focus"><label for="environment-focus">Inspect an environment</label><select id="environment-focus"><option value="">Entire knowledge store</option></select></div><button id="clear-selection">Reset focus</button></div><p id="scope" class="scope"></p><div class="network-legend"><span><i class="env-dot"></i> Environment</span><span><i class="inv-dot"></i> Invariant</span><span><i class="rule-dot"></i> Rule family</span><span><i class="source-line"></i> Found in</span><span><i class="transfer-line"></i> Transfer test</span><span><i class="similarity-line"></i> Similarity</span></div><p id="empty" role="status">Waiting for the initial subscription…</p><div id="graph"></div><p id="diagnostics"></p><details class="graph-explainer"><summary>What the connections mean</summary><p>Each large hub is an environment. Its colored satellites are invariant records extracted from reward failures; satellite colors identify failure classes. Violet diamond nodes connect shared rule families below the environment hubs.</p><p>Solid lines show where a failure was found. Dashed arrows show recorded transfer tests; inspect their outcomes before treating them as successful defenses. Dotted lines show similarity, which alone does not establish transfer.</p></details><div class="invariant-key" id="invariant-key" aria-label="Invariant records"></div></div><aside class="evidence-panel" aria-label="Selected record evidence"><div class="inspector-heading"><span class="eyebrow">EVIDENCE INSPECTOR</span><span id="selection-kind">No selection</span></div><div id="details"></div></aside></section>
<section class="audits-section" id="audits"><div class="section-heading"><div><div class="eyebrow">ENVIRONMENT RECORDS</div><h2>What has been audited</h2><p>Select an environment to inspect its failures and incoming rule applications.</p></div><span class="source-note">Scripted calibrations and model runs retain their source labels.</span></div><div class="table-scroll"><table><thead><tr><th>Environment</th><th>Source</th><th>Status</th><th>Failures</th><th>Invariants</th></tr></thead><tbody id="environments"></tbody></table></div></section>
<footer><span>Loophole · Compile environments. Check rewards. Measure learning.</span><a href="/replay.html">Compare recorded policies <span aria-hidden="true">→</span></a></footer></main>`;
const byId = (id: string) => document.getElementById(id)!;
const host = import.meta.env.VITE_SPACETIMEDB_HOST || DEFAULT_HOST;
const database = import.meta.env.VITE_SPACETIMEDB_DB || DEFAULT_DATABASE;
byId('endpoint').textContent = `${host} / ${database}`;
let snapshot: LiveSnapshot | undefined, selected: string | undefined, stop: (() => void) | undefined;
let disposeGraph: (() => void) | undefined;
type Tab = 'failure' | 'defense' | 'transfer';
let activeTab: Tab = 'failure';
const humanize = (value: string) => value.replaceAll('_', ' ').replaceAll('-', ' ');
const score = (value: number | undefined) => typeof value === 'number' && Number.isFinite(value) ? value.toLocaleString(undefined, { maximumFractionDigits: 3 }) : 'Not recorded';
const provenance = (env?: { envId: string; source: string }) => !env ? 'Source pending' : env.envId.includes('/scripted-') ? 'Scripted calibration' : env.envId.includes('/ai-') ? 'Model-generated pilot' : humanize(env.source);
function text<K extends keyof HTMLElementTagNameMap>(parent: HTMLElement, tag: K, content: string, className = ''): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag); node.textContent = content; node.className = className; parent.append(node); return node;
}
function select(id?: string) { selected = id; activeTab = 'failure'; render(); }
function section(parent: HTMLElement, title: string, value: string, className = '') {
  const block = text(parent, 'section', '', `evidence-section ${className}`);
  text(block, 'h4', title); text(block, 'p', value || 'Not included in this record.'); return block;
}
function recordButton(parent: HTMLElement, title: string, id: string) {
  const button = text(parent, 'button', title, 'evidence-link');
  button.addEventListener('click', () => select(id)); return button;
}
function payload(parent: HTMLElement, value: string) {
  const disclosure = text(parent, 'details', '', 'raw-evidence'); text(disclosure, 'summary', 'Replay evidence');
  let formatted = value; try { formatted = JSON.stringify(JSON.parse(value), null, 2); } catch { /* Some recorded details are plain text. */ }
  text(disclosure, 'pre', formatted || 'No payload attached.');
}
function details() {
  const panel = byId('details'); panel.replaceChildren();
  byId('selection-kind').textContent = selected?.startsWith('inv:') ? 'Invariant' : selected?.startsWith('env:') ? 'Environment' : selected ? 'Rule family' : 'No selection';
  if (!snapshot || !selected) {
    text(panel, 'div', '↗', 'inspector-empty-mark');
    text(panel, 'h3', 'Follow one reward failure.', 'inspector-title');
    text(panel, 'p', 'Choose a satellite to inspect the submitted answer, recorded reward, and constraint extracted from the failure.', 'inspector-intro');
    const steps = text(panel, 'ol', '', 'inspector-steps');
    for (const [title, body] of [['Inspect the failure', 'What earned reward, and why?'], ['Review the defense', 'What changed in the grader?'], ['Check transfer', 'Was the rule tested in another environment?']]) {
      const step = text(steps, 'li', ''); text(step, 'strong', title); text(step, 'p', body);
    }
    if (snapshot?.invariants.length) {
      const first = snapshot.invariants.find(i => i.envId.includes('/ai-')) ?? snapshot.invariants[0];
      recordButton(panel, 'Inspect a recorded failure →', `inv:${first.invariantId}`);
    }
    return;
  }
  if (selected.startsWith('inv:')) {
    const id = selected.slice(4), inv = snapshot.invariants.find(row => row.invariantId === id);
    const exploit = snapshot.exploits.find(row => row.invariantId === id);
    const env = snapshot.rows.environments.find(row => row.envId === (inv?.envId ?? exploit?.envId));
    const attempts = snapshot.applications.filter(row => row.invariantId === id && row.targetEnvId !== (inv?.envId ?? exploit?.envId));
    text(panel, 'span', provenance(env), 'provenance-badge');
    text(panel, 'h3', inv?.title ?? exploit?.summary ?? 'Extraction pending', 'inspector-title');
    const tabs = text(panel, 'div', '', 'evidence-tabs'); tabs.setAttribute('role', 'tablist'); tabs.setAttribute('aria-label', 'Evidence sections');
    const tabNames: Tab[] = ['failure', 'defense', 'transfer'];
    for (const name of tabNames) {
      const button = text(tabs, 'button', name === 'transfer' ? `Transfer (${attempts.length})` : name === 'failure' ? 'Failure' : 'Defense');
      button.id = `tab-${name}`; button.setAttribute('role', 'tab'); button.setAttribute('aria-selected', String(activeTab === name));
      button.setAttribute('aria-controls', 'evidence-content'); button.tabIndex = activeTab === name ? 0 : -1;
      const activate = (next: Tab) => { activeTab = next; details(); byId(`tab-${next}`).focus(); };
      button.addEventListener('click', () => activate(name));
      button.addEventListener('keydown', event => {
        let next: Tab | undefined;
        if (event.key === 'ArrowRight') next = tabNames[(tabNames.indexOf(name) + 1) % tabNames.length];
        if (event.key === 'ArrowLeft') next = tabNames[(tabNames.indexOf(name) + tabNames.length - 1) % tabNames.length];
        if (event.key === 'Home') next = 'failure';
        if (event.key === 'End') next = 'transfer';
        if (next) { event.preventDefault(); activate(next); }
      });
    }
    const content = text(panel, 'div', '', 'evidence-content'); content.id = 'evidence-content';
    content.setAttribute('role', 'tabpanel'); content.setAttribute('aria-labelledby', `tab-${activeTab}`); content.tabIndex = 0;
    if (activeTab === 'failure') {
      const scores = text(content, 'div', '', 'reward-comparison');
      for (const [title, value, tone] of [['Reward awarded', score(exploit?.rewardOriginal), 'original'], ['After repair', score(exploit?.rewardPatched), 'patched']]) {
        const card = text(scores, 'div', '', tone); text(card, 'span', title); text(card, 'strong', value, value === 'Not recorded' ? 'unmeasured' : '');
      }
      if (exploit) { const status = text(content, 'p', '', 'record-status'); text(status, 'span', 'Recorded status'); text(status, 'strong', humanize(exploit.status)); }
      section(content, 'Task under audit', env?.title ?? 'Environment record pending.');
      const completion = text(content, 'section', '', 'evidence-section'); text(completion, 'h4', 'Submitted answer');
      text(completion, 'pre', exploit?.sampleCompletion || 'No completion attached.');
      section(content, 'How it earned reward', inv?.mechanism ?? exploit?.summary ?? 'Invariant extraction has not arrived.');
      const correctness = text(content, 'div', '', 'evidence-note');
      text(correctness, 'strong', 'Reward is not a correctness verdict.');
      text(correctness, 'p', 'The scores above are grader outputs. Inspect the run’s replay evidence for the correctness check.');
    } else if (activeTab === 'defense') {
      section(content, 'Constraint to enforce', inv?.defensePattern ?? 'Invariant extraction pending.', 'defense-pattern');
      section(content, 'Root cause', inv?.rootCause ?? '');
      section(content, 'Applies when', inv?.preconditions ?? '');
      section(content, 'Recorded re-score', exploit?.rewardPatched === undefined ? 'No patched reward has been published for this failure.' : `This completion earned ${score(exploit.rewardOriginal)} before repair and ${score(exploit.rewardPatched)} after repair.`);
      section(content, 'Benign-answer checks', 'Pass counts are not included in this graph feed. Consult the run evidence before concluding that the repair preserves valid answers.');
    } else {
      if (!attempts.length) {
        section(content, 'No transfer test recorded', 'Related invariants suggest where to look. They do not establish that a defense works in another environment.');
      }
      for (const attempt of attempts) {
        const card = text(content, 'article', '', 'transfer-card');
        const target = snapshot.rows.environments.find(e => e.envId === attempt.targetEnvId);
        text(card, 'span', humanize(attempt.outcome), `outcome ${attempt.outcome === 'blocked' ? 'blocked' : 'other'}`);
        text(card, 'h4', target?.title ?? attempt.targetEnvId);
        text(card, 'p', `${provenance(target)} · ${attempt.runId}`, 'transfer-meta');
        payload(card, attempt.detail);
        if (target) recordButton(card, 'Inspect target environment →', `env:${target.envId}`);
      }
    }
    const source = text(panel, 'div', '', 'evidence-source'); text(source, 'span', 'Evidence path');
    text(source, 'code', inv?.evidencePath || exploit?.evidencePath || 'No evidence path attached.');
  } else if (selected.startsWith('env:')) {
    const env = snapshot.rows.environments.find(row => row.envId === selected!.slice(4));
    if (env) {
      text(panel, 'span', provenance(env), 'provenance-badge'); text(panel, 'h3', env.title, 'inspector-title');
      section(panel, 'Audit status', humanize(env.status));
      const members = snapshot.invariants.filter(i => i.envId === env.envId);
      text(panel, 'h4', `${members.length} extracted invariant${members.length === 1 ? '' : 's'}`, 'list-heading');
      for (const inv of members) recordButton(panel, inv.title, `inv:${inv.invariantId}`);
      if (!members.length) text(panel, 'p', 'No extracted invariant records have arrived for this environment.', 'inspector-intro');
      const transfers = snapshot.applications.filter(a => a.targetEnvId === env.envId && snapshot!.invariants.some(i => i.invariantId === a.invariantId && i.envId !== env.envId));
      if (transfers.length) {
        text(panel, 'h4', 'Rules tested here', 'list-heading');
        for (const a of transfers) {
          const inv = snapshot.invariants.find(i => i.invariantId === a.invariantId);
          const button = recordButton(panel, `${humanize(a.outcome)} · ${inv?.title ?? a.invariantId}`, `inv:${a.invariantId}`);
          button.addEventListener('click', () => { activeTab = 'transfer'; details(); });
        }
      }
    }
  } else {
    const rule = snapshot.rows.rules.find(row => row.ruleId === selected!.slice(5));
    if (rule) {
      text(panel, 'h3', rule.title, 'inspector-title');
      text(panel, 'p', `${rule.memberCount} invariant records across ${rule.envCount} environments.`, 'inspector-intro');
      section(panel, 'Shared failure class', 'These observations are grouped by mechanism. Open an invariant to inspect its preconditions and recorded transfer outcomes.');
      for (const inv of snapshot.invariants.filter(i => i.exploitClass === rule.ruleId)) recordButton(panel, inv.title, `inv:${inv.invariantId}`);
    }
  }
  text(panel, 'p', selected, 'record-id');
}
function render() {
  if (!snapshot) return;
  const focusId = document.activeElement?.id;
  const focusedNode = document.activeElement?.getAttribute('data-node-id');
  const graph = buildGraph(snapshot.rows);
  if (selected && !graph.nodes.some(n => n.id === selected)) selected = undefined;
  const envs = snapshot.rows.environments;
  const calibrationCount = envs.filter(r => r.envId.startsWith('game/scripted-')).length;
  const pilotCount = envs.filter(r => r.envId.startsWith('game/ai-')).length;
  byId('scope').textContent = `${envs.length} environments · ${calibrationCount} scripted calibrations · ${pilotCount} model-generated pilots. Selection highlights connections; the entire store stays visible.`;
  const picker = byId('environment-focus') as HTMLSelectElement;
  picker.replaceChildren(new Option('Entire knowledge store', ''));
  for (const env of envs) picker.append(new Option(env.title, `env:${env.envId}`));
  const selectedInv = snapshot.invariants.find(i => `inv:${i.invariantId}` === selected);
  picker.value = selected?.startsWith('env:') ? selected : selectedInv ? `env:${selectedInv.envId}` : '';
  const visibleIds = new Set(envs.map(row => row.envId));
  const invs = snapshot.invariants.filter(row => visibleIds.has(row.envId));
  const exploits = snapshot.exploits.filter(row => visibleIds.has(row.envId));
  const metrics = byId('metrics'); metrics.replaceChildren();
  for (const [value, name, caption] of [[envs.length, 'Environments', 'Audited or generated tasks'], [exploits.length, 'Recorded failures', 'Stored exploit observations'], [invs.length, 'Extracted invariants', 'Constraints derived from failures'], [graph.edges.filter(e => e.kind === 'applied_to').length, 'Transfer outcomes', 'Includes unsuccessful tests']]) {
    const card = text(metrics, 'div', '', 'metric'); text(card, 'span', String(name)); text(card, 'strong', String(value)); text(card, 'small', String(caption));
  }
  byId('empty').textContent = graph.nodes.length ? '' : 'Connected. No knowledge records have been published yet.';
  byId('empty').hidden = graph.nodes.length > 0;
  byId('diagnostics').textContent = graph.diagnostics.length ? `${graph.diagnostics.length} incomplete or invalid references. Some tables may still be arriving.` : '';
  disposeGraph?.();
  disposeGraph = renderGraph(byId('graph'), graph, selected, id => select(selected === id ? undefined : id));
  const key = byId('invariant-key'); key.replaceChildren();
  graph.nodes.filter(n => n.kind === 'invariant').forEach((n, i) => {
    const button = text(key, 'button', `I${i + 1}  ${n.label}`, selected === n.id ? 'active' : '');
    button.setAttribute('aria-pressed', String(selected === n.id)); button.addEventListener('click', () => select(n.id));
  });
  const body = byId('environments'); body.replaceChildren();
  for (const env of envs) {
    const tr = document.createElement('tr');
    const cell = text(tr, 'td', ''); const button = text(cell, 'button', env.title, 'audit-environment');
    button.addEventListener('click', () => { select(`env:${env.envId}`); document.querySelector('.workspace')?.scrollIntoView({ behavior: 'smooth', block: 'start' }); });
    text(cell, 'small', env.envId, 'audit-id');
    for (const value of [provenance(env), humanize(env.status), String(exploits.filter(row => row.envId === env.envId).length), String(invs.filter(row => row.envId === env.envId).length)]) text(tr, 'td', value);
    body.append(tr);
  }
  details();
  if (focusId) document.getElementById(focusId)?.focus({ preventScroll: true });
  else if (focusedNode) Array.from(byId('graph').querySelectorAll<SVGElement>('[data-node-id]')).find(node => node.getAttribute('data-node-id') === focusedNode)?.focus({ preventScroll: true });
}
function connect() {
  stop?.(); byId('error').textContent = '';
  if (!snapshot) { byId('empty').hidden = false; byId('empty').textContent = 'Waiting for the initial subscription…'; }
  stop = connectLive({
    status(state, detail) {
      byId('status').textContent = ({ connecting: snapshot ? 'Reconnecting · displayed records may be stale' : 'Connecting', subscribing: snapshot ? 'Refreshing · displayed records may be stale' : 'Loading records', live: 'Live subscription', disconnected: snapshot ? 'Disconnected · displayed records may be stale' : 'Live store unavailable', error: snapshot ? 'Connection error · displayed records may be stale' : 'Live connection failed' })[state];
      byId('light').className = state; byId('error').textContent = detail || '';
      if (!snapshot && (state === 'error' || state === 'disconnected')) byId('empty').textContent = 'The live store is unavailable. Reconnect to load its recorded audits.';
    },
    snapshot(data) { snapshot = data; byId('updated').textContent = `Updated ${new Date().toLocaleTimeString()}`; render(); },
  }, host, database);
}
byId('retry').addEventListener('click', connect);
byId('clear-selection').addEventListener('click', () => select());
byId('environment-focus').addEventListener('change', event => select((event.target as HTMLSelectElement).value || undefined));
window.addEventListener('pagehide', () => { stop?.(); disposeGraph?.(); });
details();
connect();
