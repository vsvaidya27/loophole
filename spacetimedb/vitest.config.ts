import { defineConfig, type Plugin } from 'vitest/config';
import { spacetimedbModuleTestPlugin } from 'spacetimedb/server/test-utils/vitest';

export default defineConfig({
  plugins: [spacetimedbModuleTestPlugin() as unknown as Plugin],
  test: {
    environment: 'node',
    coverage: {
      provider: 'v8',
      allowExternal: true,
      include: ['**/spacetimedb/src/graph.ts', '**/spacetimedb/src/graph_tables.ts', '**/dashboard/src/graph/buildGraph.ts'],
      reporter: ['text', 'json-summary', 'html'],
      thresholds: { lines: 90, statements: 90, functions: 90, branches: 80 },
    },
  },
});
