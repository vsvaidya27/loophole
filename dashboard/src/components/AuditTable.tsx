import type { LiveSnapshot } from '../live';
import { humanize, provenance } from '../format';

export function AuditTable({ snapshot, onSelect }: { snapshot?: LiveSnapshot; onSelect: (id: string) => void }) {
  return <section className="audits-section" id="audits">
    <div className="section-heading"><div><div className="eyebrow">ENVIRONMENT RECORDS</div><h2>What has been audited</h2><p>Select an environment to inspect its failures and incoming rule applications.</p></div><span className="source-note">Scripted calibrations and model runs retain their source labels.</span></div>
    <div className="table-scroll"><table><thead><tr><th>Environment</th><th>Source</th><th>Status</th><th>Failures</th><th>Invariants</th></tr></thead>
      <tbody id="environments">{snapshot?.rows.environments.map(env => <tr key={env.envId}>
        <td><button className="audit-environment" onClick={() => onSelect(`env:${env.envId}`)}>{env.title}</button><small className="audit-id">{env.envId}</small></td>
        <td>{provenance(env)}</td><td>{humanize(env.status)}</td>
        <td>{snapshot.exploits.filter(row => row.envId === env.envId).length}</td><td>{snapshot.invariants.filter(row => row.envId === env.envId).length}</td>
      </tr>)}</tbody>
    </table></div>
  </section>;
}
