import { defineConfig } from 'tsup';

export default defineConfig({
  entry: { index: 'src/index.ts' },
  outDir: '.',
  format: ['esm'],
  target: 'node22',
  platform: 'node',
  bundle: true,
  splitting: false,
  sourcemap: true,
  clean: false,
  // drizzle-orm is bundled, not left in node_modules: its ESM build is hundreds
  // of files under a 177 KB package.json, and Node re-reads that package scope
  // per file — ~200 ms of the API's cold-start CPU (Vercel Fluid bills cold
  // starts). Its drivers (pg, @neondatabase/serverless) stay external.
  noExternal: [/^@rsmm\//, /^drizzle-orm(\/|$)/],
  esbuildPlugins: [
    {
      name: 'externalize-node-modules',
      setup(build) {
        build.onResolve({ filter: /.*/ }, (args) => {
          if (args.kind === 'entry-point') return;
          if (args.path.startsWith('.') || args.path.startsWith('/')) return;
          if (args.path.startsWith('@rsmm/')) return;
          if (args.path === 'drizzle-orm' || args.path.startsWith('drizzle-orm/')) return;
          return { path: args.path, external: true };
        });
      },
    },
  ],
});
