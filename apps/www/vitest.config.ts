import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    globals: true,
    // Only plain-module tests live here; the app's components are exercised by
    // the build and by the live-page checks, not by jsdom.
    include: ['src/**/*.test.ts'],
  },
});
