import { schema, type InferSchema, type ReducerCtx } from 'spacetimedb/server';
import { coreTables } from './core_tables';
import { graphTables } from './graph_tables';
import { accessTables } from './access_tables';

const spacetimedb = schema({ ...coreTables, ...graphTables, ...accessTables });
export default spacetimedb;

// Typed context for helpers outside reducer bodies: import { type Ctx } from './schema'.
export type Ctx = ReducerCtx<InferSchema<typeof spacetimedb>>;
