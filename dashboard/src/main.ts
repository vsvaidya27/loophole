import './style.css';
import { connectLive, buildGraph, DEFAULT_DATABASE, DEFAULT_HOST, type LiveSnapshot } from './live';

const app = document.querySelector<HTMLDivElement>('#app')!;
app.innerHTML = `<main><header><div class="eyebrow">LOOPHOLE / LIVE OBSERVATORY</div><h1>Every exploit becomes knowledge.</h1><p>Watch confirmed records arrive from the hardening pipeline. Select a node to inspect its evidence.</p><nav><a aria-current="page" href="/">Live knowledge graph</a><a href="/replay.html">Game & training replays</a></nav></header>
<section class="connection"><div><span id="light"></span><strong id="status">Connecting</strong><span id="updated"></span></div><button id="retry">Reconnect</button><p id="endpoint"></p><p id="error" role="alert"></p></section>
<section class="metrics" id="metrics" aria-live="polite"></section>
<section class="workspace"><div class="graph-panel"><div class="toolbar"><h2>Knowledge graph</h2><label><input id="hide-seed" type="checkbox" checked> Hide seed examples</label></div><div class="legend"><span>● Environment</span><span>● Invariant</span><span>● Rule</span><span>Lines: source · membership · similarity · transfer</span></div><p id="empty">Waiting for the initial subscription…</p><div id="graph"></div><p id="diagnostics"></p></div><aside><h2>Record details</h2><div id="details">Select a node. Recorded outcomes require target-specific evidence; similarity alone does not prove a defense works.</div></aside></section>
<section><h2>Audit records</h2><p>These are records received from the service. Scripted probes, recorded runs, and model-driven audits must retain their provenance.</p><div class="table-scroll"><table><thead><tr><th>Environment</th><th>Status</th><th>Exploits</th><th>Invariants</th></tr></thead><tbody id="environments"></tbody></table></div></section>
<footer>No writer credential is loaded by this page. Live data comes from the public service subscription.</footer></main>`;
const byId = (id: string) => document.getElementById(id)!;
const host = import.meta.env.VITE_SPACETIMEDB_HOST || DEFAULT_HOST;
const database = import.meta.env.VITE_SPACETIMEDB_DB || DEFAULT_DATABASE;
byId('endpoint').textContent = `${host} / ${database}`;
let snapshot: LiveSnapshot | undefined, selected: string | undefined, stop: (() => void) | undefined;
let hideSeed = true;
function text(parent: HTMLElement, tag: string, content: string, className = '') {
  const node = document.createElement(tag); node.textContent = content; node.className = className; parent.append(node); return node;
}
function details() {
  const panel = byId('details'); panel.replaceChildren();
  if (!snapshot || !selected) { text(panel, 'p', 'Select a node to see its source and stored evidence.'); return; }
  text(panel, 'h3', selected);
  if (selected.startsWith('inv:')) {
    const id = selected.slice(4), inv = snapshot.invariants.find(row => row.invariantId === id);
    const exploit = snapshot.exploits.find(row => row.invariantId === id);
    if (inv) for (const [label, value] of [['Mechanism', inv.mechanism], ['Root cause', inv.rootCause], ['Preconditions', inv.preconditions], ['Defense pattern', inv.defensePattern], ['Evidence path', inv.evidencePath]]) {
      text(panel, 'h4', label); text(panel, 'p', value);
    }
    if (exploit) { text(panel, 'h4', 'Recorded exploit'); text(panel, 'p', exploit.summary); text(panel, 'p', `Original reward ${exploit.rewardOriginal}; patched ${exploit.rewardPatched ?? 'not measured'}`); text(panel, 'pre', exploit.sampleCompletion); }
    for (const attempt of snapshot.applications.filter(row => row.invariantId === id)) {
      text(panel, 'h4', `${attempt.outcome} → ${attempt.targetEnvId}`); text(panel, 'p', `Run: ${attempt.runId}`); text(panel, 'pre', attempt.detail);
    }
    if (!inv) text(panel, 'p', 'Pending extraction: exploit recorded, invariant has not arrived.');
  } else if (selected.startsWith('env:')) {
    const env = snapshot.rows.environments.find(row => row.envId === selected!.slice(4));
    if (env) { text(panel, 'p', `${env.title} · ${env.source} · ${env.status}`); text(panel, 'p', env.envId); }
  } else {
    const rule = snapshot.rows.rules.find(row => row.ruleId === selected!.slice(5));
    if (rule) text(panel, 'p', `${rule.title}: ${rule.memberCount} invariants across ${rule.envCount} environments.`);
  }
}
function render() {
  if (!snapshot) return;
  const graph = buildGraph(snapshot.rows, { hideSeed });
  const envs = snapshot.rows.environments.filter(row => !hideSeed || row.source !== 'seed');
  const visibleIds = new Set(envs.map(row => row.envId));
  const invs = snapshot.invariants.filter(row => visibleIds.has(row.envId));
  const exploits = snapshot.exploits.filter(row => visibleIds.has(row.envId));
  const metrics = byId('metrics'); metrics.replaceChildren();
  for (const [value, label] of [[envs.length, 'environments'], [exploits.length, 'recorded exploits'], [invs.length, 'invariants'], [graph.edges.filter(e => e.kind === 'applied_to').length, 'transfer outcomes']]) {
    const card = text(metrics, 'div', '', 'metric'); text(card, 'strong', String(value)); text(card, 'span', String(label));
  }
  byId('empty').textContent = graph.nodes.length ? '' : 'Connected, no knowledge records yet. Run an audit and push its validated results to see the graph grow.';
  byId('empty').hidden = graph.nodes.length > 0;
  byId('diagnostics').textContent = graph.diagnostics.length ? `${graph.diagnostics.length} incomplete or invalid references. Some tables may still be arriving.` : '';
  const container = byId('graph'); container.replaceChildren();
  const ns = 'http://www.w3.org/2000/svg';
  const svg = document.createElementNS(ns, 'svg'); svg.setAttribute('viewBox', `0 0 1100 ${Math.max(360, graph.nodes.length * 42)}`); svg.setAttribute('role', 'group'); svg.setAttribute('aria-label', 'Live knowledge graph');
  const positions = new Map<string, [number, number]>();
  const columns = { environment: 145, invariant: 540, rule: 950 }, counts = { environment: 0, invariant: 0, rule: 0 };
  for (const node of graph.nodes) positions.set(node.id, [columns[node.kind], 55 + counts[node.kind]++ * 75]);
  const height = Math.max(360, Math.max(...Object.values(counts)) * 75 + 50);
  svg.setAttribute('viewBox', `0 0 1100 ${height}`); svg.style.height = `${height}px`;
  for (const edge of graph.edges) {
    const a = positions.get(edge.source)!, b = positions.get(edge.target)!;
    const line = document.createElementNS(ns, 'line');
    for (const [key, value] of Object.entries({ x1: a[0], y1: a[1], x2: b[0], y2: b[1] })) line.setAttribute(key, String(value));
    line.setAttribute('class', `edge ${edge.kind}`); const title = document.createElementNS(ns, 'title'); title.textContent = `${edge.kind}${edge.outcome ? ': ' + edge.outcome : ''}${edge.weight === undefined ? '' : ' ' + edge.weight.toFixed(2)}`; line.append(title); svg.append(line);
  }
  for (const node of graph.nodes) {
    const [x, y] = positions.get(node.id)!;
    const group = document.createElementNS(ns, 'g'); group.setAttribute('class', `node ${node.kind}${selected === node.id ? ' selected' : ''}`); group.setAttribute('role', 'button'); group.setAttribute('tabindex', '0'); group.setAttribute('aria-label', node.label);
    const circle = document.createElementNS(ns, 'circle'); circle.setAttribute('cx', String(x)); circle.setAttribute('cy', String(y)); circle.setAttribute('r', '12');
    const label = document.createElementNS(ns, 'text'); label.setAttribute('x', String(x)); label.setAttribute('y', String(y + 30)); label.setAttribute('text-anchor', 'middle'); label.textContent = node.label.length > 34 ? node.label.slice(0, 31) + '…' : node.label;
    const title = document.createElementNS(ns, 'title'); title.textContent = node.id;
    const choose = () => { selected = node.id; render(); };
    group.addEventListener('click', choose); group.addEventListener('keydown', event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); choose(); } });
    group.append(circle, label, title); svg.append(group);
  }
  if (graph.nodes.length) container.append(svg);
  const body = byId('environments'); body.replaceChildren();
  for (const env of envs) {
    const tr = document.createElement('tr');
    for (const value of [env.envId, env.status, String(exploits.filter(row => row.envId === env.envId).length), String(invs.filter(row => row.envId === env.envId).length)]) text(tr, 'td', value);
    body.append(tr);
  }
  details();
}
function connect() {
  stop?.(); snapshot = undefined; byId('error').textContent = ''; byId('empty').hidden = false; byId('empty').textContent = 'Waiting for the initial subscription…';
  stop = connectLive({
    status(state, detail) {
      byId('status').textContent = ({ connecting: 'Connecting', subscribing: 'Loading tables', live: 'Live subscription', disconnected: 'Disconnected · displayed data may be stale', error: 'Connection error · displayed data may be stale' })[state];
      byId('light').className = state;
      byId('error').textContent = detail || '';
    },
    snapshot(data) { snapshot = data; byId('updated').textContent = `Updated ${new Date().toLocaleTimeString()}`; render(); },
  }, host, database);
}
byId('retry').addEventListener('click', connect);
byId('hide-seed').addEventListener('change', event => { hideSeed = (event.target as HTMLInputElement).checked; render(); });
window.addEventListener('pagehide', () => stop?.());
connect();
