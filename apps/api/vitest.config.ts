import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    // Emails usually land in seconds, but delivery can spike to minutes on
    // edge cases. Give the e2e room; it resolves early on the first match.
    testTimeout: 5 * 60 * 1000,
    hookTimeout: 60 * 1000,
    // One DB / one inbox — don't run files in parallel against shared state.
    fileParallelism: false,
  },
});
