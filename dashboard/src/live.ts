import { DbConnection } from './module_bindings';
import { buildGraph, type GraphRows } from './graph/buildGraph';

export const DEFAULT_HOST = 'wss://maincloud.spacetimedb.com';
export const DEFAULT_DATABASE = 'loophole-knowledge-calhacks-2026';
export const PUBLIC_QUERIES = [
  'SELECT * FROM environment', 'SELECT * FROM exploit', 'SELECT * FROM invariant',
  'SELECT * FROM rule', 'SELECT * FROM similarity_edge', 'SELECT * FROM rule_application',
];
export type LiveSnapshot = ReturnType<typeof readSnapshot>;
export function readSnapshot(connection: DbConnection) {
  const db = connection.db;
  const rows: GraphRows = {
    environments: [...db.environment.iter()], exploits: [...db.exploit.iter()],
    invariants: [...db.invariant.iter()], rules: [...db.rule.iter()],
    similarityEdges: [...db.similarityEdge.iter()], ruleApplications: [...db.ruleApplication.iter()],
  };
  return { rows, invariants: [...db.invariant.iter()], exploits: [...db.exploit.iter()], applications: [...db.ruleApplication.iter()] };
}
export type LiveHandlers = {
  status: (state: 'connecting' | 'subscribing' | 'live' | 'disconnected' | 'error', detail?: string) => void;
  snapshot: (data: LiveSnapshot) => void;
};

/** Event-driven subscription: no SQL polling and no writer token in the browser. */
export function watchConnection(connection: DbConnection, handlers: LiveHandlers) {
  let ready = false, closed = false, queued = false;
  const publish = () => {
    if (!ready || closed || queued) return;
    queued = true;
    queueMicrotask(() => { queued = false; if (!closed && ready) handlers.snapshot(readSnapshot(connection)); });
  };
  const tables = [connection.db.environment, connection.db.exploit, connection.db.invariant,
    connection.db.rule, connection.db.similarityEdge, connection.db.ruleApplication];
  for (const table of tables) { table.onInsert(publish); table.onUpdate(publish); table.onDelete(publish); }
  handlers.status('subscribing');
  const subscription = connection.subscriptionBuilder()
    .onApplied(() => { ready = true; handlers.status('live'); publish(); })
    .onError(ctx => { ready = false; handlers.status('error', String(ctx.event)); })
    .subscribe(PUBLIC_QUERIES);
  return () => {
    closed = true;
    for (const table of tables) { table.removeOnInsert(publish); table.removeOnUpdate(publish); table.removeOnDelete(publish); }
    subscription.unsubscribe();
  };
}

export function connectLive(handlers: LiveHandlers, host = DEFAULT_HOST, database = DEFAULT_DATABASE) {
  let stopWatching: (() => void) | undefined;
  let stopped = false;
  const active: LiveHandlers = {
    status: (...args) => { if (!stopped) handlers.status(...args); },
    snapshot: data => { if (!stopped) handlers.snapshot(data); },
  };
  handlers.status('connecting');
  const connection = DbConnection.builder().withUri(host).withDatabaseName(database)
    .onConnect(conn => { if (stopped) conn.disconnect(); else stopWatching = watchConnection(conn, active); })
    .onConnectError((_ctx, error) => active.status('error', String(error)))
    .onDisconnect((_ctx, error) => active.status('disconnected', error ? String(error) : 'Connection closed'))
    .build();
  return () => { stopped = true; stopWatching?.(); connection.disconnect(); };
}
export { buildGraph };
