import { describe, it, expect, vi } from 'vitest';
import type { DbConnection } from './module_bindings';
import { PUBLIC_QUERIES, watchConnection } from './live';

function fixture() {
  const table = () => ({ iter: () => [], onInsert: vi.fn(), onUpdate: vi.fn(), onDelete: vi.fn(), removeOnInsert: vi.fn(), removeOnUpdate: vi.fn(), removeOnDelete: vi.fn() });
  const db = { environment: table(), exploit: table(), invariant: table(), rule: table(), similarityEdge: table(), ruleApplication: table() };
  const handle = { unsubscribe: vi.fn() };
  const builder = { onApplied: vi.fn(), onError: vi.fn(), subscribe: vi.fn(() => handle) };
  builder.onApplied.mockReturnValue(builder); builder.onError.mockReturnValue(builder);
  const connection = { db, subscriptionBuilder: () => builder } as unknown as DbConnection;
  return { db, builder, handle, connection, handlers: { status: vi.fn(), snapshot: vi.fn() } };
}
describe('live dashboard subscriptions', () => {
  it('subscribes only to public graph inputs and waits for initial tables', async () => {
    const t = fixture(); watchConnection(t.connection, t.handlers);
    expect(t.builder.subscribe).toHaveBeenCalledWith(PUBLIC_QUERIES);
    expect(PUBLIC_QUERIES.some(query => /embedding|access_|token/.test(query))).toBe(false);
    t.db.environment.onInsert.mock.calls[0][0](); await Promise.resolve();
    expect(t.handlers.snapshot).not.toHaveBeenCalled();
    t.builder.onApplied.mock.calls[0][0](); await Promise.resolve();
    expect(t.handlers.status).toHaveBeenLastCalledWith('live');
    expect(t.handlers.snapshot.mock.calls[0][0].rows.environments).toEqual([]);
  });
  it('coalesces mutations and refreshes every subscribed table without polling', async () => {
    const t = fixture(); watchConnection(t.connection, t.handlers);
    t.builder.onApplied.mock.calls[0][0](); await Promise.resolve(); t.handlers.snapshot.mockClear();
    for (const table of Object.values(t.db)) for (const method of [table.onInsert, table.onUpdate, table.onDelete]) method.mock.calls[0][0]();
    await Promise.resolve(); expect(t.handlers.snapshot).toHaveBeenCalledTimes(1);
  });
  it('removes handlers and cancels queued renders on teardown', async () => {
    const t = fixture(); const stop = watchConnection(t.connection, t.handlers);
    t.builder.onApplied.mock.calls[0][0](); stop(); await Promise.resolve();
    expect(t.handlers.snapshot).not.toHaveBeenCalled(); expect(t.handle.unsubscribe).toHaveBeenCalledOnce();
    for (const table of Object.values(t.db)) expect(table.removeOnInsert).toHaveBeenCalledWith(table.onInsert.mock.calls[0][0]);
  });
  it('shows subscription failures without publishing an empty graph as live data', async () => {
    const t = fixture(); watchConnection(t.connection, t.handlers);
    t.builder.onApplied.mock.calls[0][0]();
    t.builder.onError.mock.calls[0][0]({ event: new Error('denied') }); await Promise.resolve();
    expect(t.handlers.status).toHaveBeenLastCalledWith('error', 'Error: denied');
    expect(t.handlers.snapshot).not.toHaveBeenCalled();
  });
});
