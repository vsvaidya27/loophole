import { SenderError } from 'spacetimedb/server';
import type { Ctx } from './schema';

export function requireOwner(ctx: Ctx) {
  if (ctx.db.access_owner.id.find(0)?.identity !== ctx.sender.toHexString()) {
    throw new SenderError('Only the database publisher can manage writers');
  }
}
export function requireWriter(ctx: Ctx) {
  const identity = ctx.sender.toHexString();
  if (ctx.db.access_owner.id.find(0)?.identity !== identity && !ctx.db.access_writer.identity.find(identity)) {
    throw new SenderError('Writer access required; ask the database owner to authorize your identity');
  }
}
