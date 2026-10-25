import { LIVE_DATABASE, LIVE_HOST, type useLiveStore } from '../hooks/useLiveStore';

export function ConnectionStatus({ status, detail, snapshot, updatedAt, reconnect }: ReturnType<typeof useLiveStore>) {
  const label = {
    connecting: snapshot ? 'Reconnecting · displayed records may be stale' : 'Connecting',
    subscribing: snapshot ? 'Refreshing · displayed records may be stale' : 'Loading records',
    live: 'Live subscription',
    disconnected: snapshot ? 'Disconnected · displayed records may be stale' : 'Live store unavailable',
    error: snapshot ? 'Connection error · displayed records may be stale' : 'Live connection failed',
  }[status];
  return <section className="connection" aria-label="Live connection">
    <div><span id="light" className={status} /><strong id="status" role="status">{label}</strong><span id="updated">{updatedAt && `Updated ${updatedAt.toLocaleTimeString()}`}</span></div>
    <button id="retry" onClick={reconnect}>Reconnect</button>
    <details className="connection-details"><summary>Connection details</summary><p id="endpoint">{LIVE_HOST} / {LIVE_DATABASE}</p></details>
    <p id="error" role="alert">{detail}</p>
  </section>;
}
