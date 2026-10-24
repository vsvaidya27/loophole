import { table, t } from 'spacetimedb/server';

// Private metadata. Knowledge tables remain publicly readable.
export const accessTables = {
  access_owner: table({ name: 'access_owner' }, { id: t.u32().primaryKey(), identity: t.string() }),
  access_writer: table({ name: 'access_writer' }, { identity: t.string().primaryKey() }),
};
