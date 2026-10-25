import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  build: {
    rollupOptions: {
      input: {
        main: new URL('./index.html', import.meta.url).pathname,
        demo: new URL('./demo.html', import.meta.url).pathname,
      },
    },
  },
  server: { proxy: { '/api/hub-demo': { target: 'http://127.0.0.1:8788' } } },
});
