import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';

const { app } = JSON.parse(
  readFileSync(new URL('../../src-tauri/tauri.conf.json', import.meta.url), 'utf8'),
);
const directives = new Map<string, string[]>(
  app.security.csp.split(';').map((directive: string) => {
    const [name, ...sources] = directive.trim().split(/\s+/);
    return [name, sources];
  }),
);

describe('desktop image policy', () => {
  it.each([
    'https://*.googleusercontent.com',
    'https://cdn.discordapp.com',
    'https://avatars.githubusercontent.com',
  ])('allows %s avatars only as images', (source) => {
    expect(directives.get('img-src')).toContain(source);
    for (const [directive, sources] of directives) {
      if (directive !== 'img-src') expect(sources).not.toContain(source);
    }
  });

  it('keeps bundled art and registry uploads without allowing arbitrary image hosts', () => {
    expect(directives.get('img-src')).toEqual(
      expect.arrayContaining([
        "'self'",
        'data:',
        'blob:',
        'https://api.rsmm.me',
        'https://s3-rsmm.me',
        'https://cdn.rsmm.me',
        'https://s3-ravenswatch.ovilli.de',
      ]),
    );
    expect(directives.get('img-src')).not.toContain('*');
    expect(directives.get('img-src')).not.toContain('https:');
    expect(directives.get('default-src')).toEqual(["'self'"]);
    expect(directives.get('script-src')).toEqual(["'self'"]);
    expect(directives.get('object-src')).toEqual(["'none'"]);
  });
});
