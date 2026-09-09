import {defineConfig} from 'vite';
import {resolve} from 'node:path';

export default defineConfig({
  // Vite 8 only accepts "./" as a relative base. The post transform adds the
  // backend-facing "assets/" mount while assetsDir keeps emitted files flat.
  base: './',
  plugins: [{
    name: 'chattodo-assets-mount',
    transformIndexHtml: {order: 'post', handler: html=>html.replaceAll('src="./','src="./assets/').replaceAll('href="./','href="./assets/')},
  }],
  build: {
    outDir: resolve(import.meta.dirname, '../../src/chatsite/todo_static'),
    emptyOutDir: true,
    sourcemap: false,
    assetsDir: '',
    // Rolldown chunk hashes include build-root metadata even for identical code.
    // Stable entry names keep committed rebuilds portable; serving uses no-store.
    rollupOptions: {output: {entryFileNames: 'todo-native.js', chunkFileNames: 'chunk-[name].js', assetFileNames: '[name]-[hash][extname]'}},
  },
});
