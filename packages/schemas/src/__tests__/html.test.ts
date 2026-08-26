import { describe, expect, it } from 'vitest';
import { jsonLd } from '../index';

describe('jsonLd', () => {
  it('is still valid JSON describing the same value', () => {
    const value = { '@type': 'SoftwareApplication', name: 'A Mod', count: 3, ok: true };
    expect(JSON.parse(jsonLd(value))).toEqual(value);
  });

  it('makes a </script> breakout impossible', () => {
    // The exact payload a publisher would put in a mod name to escape the
    // ld+json block and inject markup into rsmm.me.
    const payload = 'Cool Mod</script><img src=x onerror=alert(document.cookie)>';
    const out = jsonLd({ name: payload });

    expect(out).not.toContain('</script');
    expect(out).not.toContain('<');
    expect(out).not.toContain('>');
    // …and the value still round-trips intact, so the page's structured data
    // stays truthful rather than being mangled.
    expect(JSON.parse(out).name).toBe(payload);
  });

  it('escapes ampersands so the payload survives entity decoding too', () => {
    const out = jsonLd({ name: '&lt;script&gt;' });
    expect(out).not.toContain('&');
    expect(JSON.parse(out).name).toBe('&lt;script&gt;');
  });

  it('escapes U+2028 / U+2029, which are legal in JSON but terminate a JS line', () => {
    const value = { name: 'a b c' };
    const out = jsonLd(value);
    expect(out).not.toContain(' ');
    expect(out).not.toContain(' ');
    expect(JSON.parse(out).name).toBe('a b c');
  });

  it('escapes payloads nested anywhere in the graph', () => {
    const out = jsonLd({
      '@graph': [{ author: { '@type': 'Person', name: '</script><svg onload=alert(1)>' } }],
    });
    expect(out).not.toContain('</script');
    expect(out).not.toContain('<');
  });

  it('leaves ordinary content readable', () => {
    expect(jsonLd({ name: 'Damage Meter' })).toBe('{"name":"Damage Meter"}');
  });
});
