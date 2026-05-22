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
  noExternal: [/^@rsmm\//],
  esbuildPlugins: [
    {
      name: 'externalize-node-modules',
      setup(build) {
        build.onResolve({ filter: /.*/ }, (args) => {
          if (args.kind === 'entry-point') return;
          if (args.path.startsWith('.') || args.path.startsWith('/')) return;
          if (args.path.startsWith('@rsmm/')) return;
          return { path: args.path, external: true };
        });
      },
    },
  ],
});
