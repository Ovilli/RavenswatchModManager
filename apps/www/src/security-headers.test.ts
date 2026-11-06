import { afterEach, describe, expect, it, vi } from 'vitest';
import nextConfig from '../next.config.mjs';

afterEach(() => vi.unstubAllEnvs());

describe('production Content Security Policy', () => {
  it('allows blob image previews without allowing blob scripts or connections', async () => {
    vi.stubEnv('NODE_ENV', 'production');
    const rules = await nextConfig.headers?.();
    expect(rules).toBeDefined();
    const csp = rules
      ?.find((rule) => rule.source === '/(.*)')
      ?.headers.find((header) => header.key === 'Content-Security-Policy')?.value;
    expect(csp).toBeDefined();

    const directives = new Map(
      csp?.split('; ').map((directive) => {
        const [name, ...sources] = directive.split(' ');
        return [name, sources];
      }),
    );
    expect(directives.get('img-src')).toContain('blob:');
    for (const directive of ['default-src', 'script-src', 'connect-src', 'frame-src']) {
      expect(directives.get(directive)).toBeDefined();
      expect(directives.get(directive)).not.toContain('blob:');
    }
    expect(directives.get('object-src')).toEqual(["'none'"]);
  });
});
