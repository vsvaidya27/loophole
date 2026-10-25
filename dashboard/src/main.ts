import './style.css';
import { renderGraph } from './graph/renderGraph';
import { connectLive, buildGraph, DEFAULT_DATABASE, DEFAULT_HOST, type LiveSnapshot } from './live';

const app = document.querySelector<HTMLDivElement>('#app')!;
app.innerHTML = `<main><header><div class="eyebrow">LOOPHOLE / LIVE OBSERVATORY</div><h1>Every exploit becomes knowledge.</h1><p>Watch confirmed records arrive from the hardening pipeline. Select a node to inspect its evidence.</p><nav><a aria-current="page" href="/">Live knowledge graph</a><a href="/replay.html">Game & training replays</a></nav></header>
<section class="connection"><div><span id="light"></span><strong id="status">Connecting</strong><span id="updated"></span></div><button id="retry">Reconnect</button><p id="endpoint"></p><p id="error" role="alert"></p></section>
<section class="metrics" id="metrics" aria-live="polite"></section>
<section class="workspace"><div class="graph-panel"><div class="toolbar"><div><div class="eyebrow">THE ENTIRE KNOWLEDGE STORE</div><h2>From local failures to shared defenses.</h2></div><button id="clear-selection">Reset focus</button></div><p id="scope" class="scope"></p><div class="network-legend"><span><i class="env-dot"></i> Environment</span><span><i class="inv-dot"></i> Invariant</span><span><i class="rule-dot"></i> Shared rule family</span><span><i class="source-line"></i> Discovered in</span><span><i class="transfer-line"></i> Tested transfer</span><span><i class="similarity-line"></i> Similarity</span></div><p id="empty">Waiting for the initial subscription…</p><div id="graph"></div><p id="diagnostics"></p><div class="graph-explainer"><strong>How to read this graph</strong><p>Large blue nodes are environments. Small amber nodes are invariants extracted from observed failures. Shaded regions group invariants about the same rule family. Green dashed arrows record tests on another environment; purple dotted links show similarity, not proven transfer.</p><p>An invariant is a constraint the grader should consistently enforce—for example, reject conflicting final answers. Each record stores the observed failure, its preconditions, and a defense. Its validity is supported by replay evidence, not a universal proof.</p></div><div id="invariant-key" class="invariant-key"></div></div><aside><h2>Explore the evidence</h2><div id="details"></div></aside></section>
<section><h2>Audit records</h2><p>These are records received from the service. Scripted probes, recorded runs, and model-driven audits must retain their provenance.</p><div class="table-scroll"><table><thead><tr><th>Environment</th><th>Status</th><th>Exploits</th><th>Invariants</th></tr></thead><tbody id="environments"></tbody></table></div></section>
<footer>No writer credential is loaded by this page. Live data comes from the public service subscription.</footer></main>`;
const byId = (id: string) => document.getElementById(id)!;
const host = import.meta.env.VITE_SPACETIMEDB_HOST || DEFAULT_HOST;
const database = import.meta.env.VITE_SPACETIMEDB_DB || DEFAULT_DATABASE;
byId('endpoint').textContent = `${host} / ${database}`;
let snapshot: LiveSnapshot | undefined, selected: string | undefined, stop: (() => void) | undefined;
let disposeGraph: (() => void) | undefined;
function text(parent: HTMLElement, tag: string, content: string, className = '') {
  const node = document.createElement(tag); node.textContent = content; node.className = className; parent.append(node); return node;
}
function details() {
  const panel = byId('details'); panel.replaceChildren();
  if (!snapshot || !selected) { text(panel, 'p', 'Select a blue environment, an amber invariant, or a shaded rule family. The graph always shows the entire store; selection highlights related evidence.'); return; }
  if (selected.startsWith('inv:')) {
    const id = selected.slice(4), inv = snapshot.invariants.find(row => row.invariantId === id);
    const exploit = snapshot.exploits.find(row => row.invariantId === id);
    if (inv) text(panel, 'h3', inv.title);
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
    if (env) {
      text(panel, 'h3', env.title); text(panel, 'p', `${env.envId.includes('/scripted-') ? 'Scripted calibration' : (env.envId.includes('/ai-') || env.title.includes('model-generated')) ? 'Model-generated pilot' : env.source} · ${env.status}`);
      const members = snapshot.invariants.filter(i => i.envId === env.envId);
      text(panel, 'h4', `${members.length} invariant records extracted here`);
      for (const inv of members) {
        const button = text(panel, 'button', inv.title, 'evidence-link');
        button.addEventListener('click', () => { selected = `inv:${inv.invariantId}`; render(); });
      }
      const transfers = snapshot.applications.filter(a => a.targetEnvId === env.envId);
      if (transfers.length) {
        text(panel, 'h4', 'Rules tested on this environment');
        for (const a of transfers) text(panel, 'p', `${a.outcome} · ${a.invariantId}`);
      }
    }
  } else {
    const rule = snapshot.rows.rules.find(row => row.ruleId === selected!.slice(5));
    if (rule) { text(panel, 'h3', rule.title); text(panel, 'p', `${rule.memberCount} invariant records from ${rule.envCount} environments. These are related observations grouped by failure class, not a claim that every defense applies everywhere.`); }
  }
  text(panel, 'p', selected, 'record-id');
}
function render() {
  if (!snapshot) return;
  const graph = buildGraph(snapshot.rows);
  if (selected && !graph.nodes.some(n => n.id === selected)) selected = undefined;
  const envs = snapshot.rows.environments;
  const calibrationCount = envs.filter(r => r.envId.startsWith('game/scripted-')).length;
  byId('scope').textContent = `All ${envs.length} environments · ${calibrationCount} scripted calibration records · ${envs.filter(r => (r.envId.startsWith('game/ai-') || r.title.includes('model-generated'))).length} model-generated pilot${envs.filter(r => (r.envId.startsWith('game/ai-') || r.title.includes('model-generated'))).length === 1 ? '' : 's'}. Select any node or cluster to follow its evidence.`;
  const visibleIds = new Set(envs.map(row => row.envId));
  const invs = snapshot.invariants.filter(row => visibleIds.has(row.envId));
  const exploits = snapshot.exploits.filter(row => visibleIds.has(row.envId));
  const metrics = byId('metrics'); metrics.replaceChildren();
  for (const [value, label] of [[envs.length, envs.length === 1 ? 'environment' : 'environments'], [exploits.length, 'recorded exploits'], [invs.length, 'invariant records'], [graph.edges.filter(e => e.kind === 'applied_to').length, 'transfer outcomes']]) {
    const card = text(metrics, 'div', '', 'metric'); text(card, 'strong', String(value)); text(card, 'span', String(label));
  }
  byId('empty').textContent = graph.nodes.length ? '' : 'Connected, no knowledge records yet. Run an audit and push its validated results to see the graph grow.';
  byId('empty').hidden = graph.nodes.length > 0;
  byId('diagnostics').textContent = graph.diagnostics.length ? `${graph.diagnostics.length} incomplete or invalid references. Some tables may still be arriving.` : '';
  disposeGraph?.();
  disposeGraph = renderGraph(byId('graph'), graph, selected, id => { selected = selected === id ? undefined : id; render(); });
  const key = byId('invariant-key'); key.replaceChildren();
  graph.nodes.filter(n => n.kind === 'invariant').forEach((n, i) => {
    const button = text(key, 'button', `I${i + 1}  ${n.label}`, selected === n.id ? 'active' : '');
    button.addEventListener('click', () => { selected = n.id; render(); });
  });
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
byId('clear-selection').addEventListener('click', () => { selected = undefined; render(); });
window.addEventListener('pagehide', () => stop?.());
connect();
