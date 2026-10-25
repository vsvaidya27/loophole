import { SenderError, t } from 'spacetimedb/server';
import spacetimedb from './schema';
import { requireOwner } from './access';

export const init = spacetimedb.init(ctx => {
  // On first publish the sender is the publishing identity. No knowledge is seeded.
  ctx.db.access_owner.insert({ id: 0, identity: ctx.sender.toHexString() });
});

export const set_writer = spacetimedb.reducer(
  { identity: t.string(), enabled: t.bool() },
  (ctx, { identity, enabled }) => {
    requireOwner(ctx);
    if (!/^[0-9a-f]{64}$/.test(identity)) throw new SenderError('identity must be 64 lowercase hex characters');
    if (enabled && !ctx.db.access_writer.identity.find(identity)) ctx.db.access_writer.insert({ identity });
    if (!enabled) ctx.db.access_writer.identity.delete(identity);
  },
);
