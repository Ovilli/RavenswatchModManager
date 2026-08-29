import { describe, expect, it } from 'vitest';
import { markdownToText, renderMarkdown } from './markdown';

/**
 * `renderMarkdown` output goes straight to `dangerouslySetInnerHTML` on a page
 * that renders arbitrary user-submitted Markdown, so these are the load-bearing
 * tests in this app: a regression here is stored XSS, not a layout bug.
 */
describe('renderMarkdown — sanitization', () => {
  const vectors: [name: string, source: string][] = [
    ['raw script tag', '<script>alert(1)</script>'],
    ['img onerror handler', '<img src=x onerror="alert(1)">'],
    ['javascript: link', '[click](javascript:alert(1))'],
    ['data: image payload', '![x](data:text/html;base64,PHNjcmlwdD5hbGVydCgxKTwvc2NyaXB0Pg==)'],
    ['iframe', '<iframe src="https://evil.tld"></iframe>'],
    ['svg onload', '<svg onload="alert(1)">'],
    ['style tag', '<style>body{display:none}</style>'],
    ['credential-harvesting form', '<form action="https://evil.tld"><input name="pw"></form>'],
    ['protocol-relative link', '[x](//evil.tld)'],
    ['inline event handler', '<p onclick="alert(1)">hi</p>'],
    ['object embed', '<object data="https://evil.tld"></object>'],
    ['base tag', '<base href="https://evil.tld/">'],
  ];

  for (const [name, source] of vectors) {
    it(`strips ${name}`, () => {
      const html = renderMarkdown(source);
      expect(html).not.toMatch(
        /<script|<iframe|<style|<form|<input|<svg|<object|<base|on[a-z]+=|javascript:|data:text\/html/i,
      );
      // evil.tld may survive as link TEXT; it must never survive as a target.
      expect(html).not.toMatch(/(href|src|action|data)\s*=\s*["']?(\/\/|[a-z]+:)?[^"'>]*evil\.tld/i);
    });
  }

  it('keeps the markup Markdown is actually for', () => {
    const html = renderMarkdown('## Title\n\n- one\n- two\n\n**bold** and `code`');
    expect(html).toContain('<h2>Title</h2>');
    expect(html).toContain('<li>one</li>');
    expect(html).toContain('<strong>bold</strong>');
    expect(html).toContain('<code>code</code>');
  });

  it('marks outbound links nofollow and noopener', () => {
    // Regression: `rel`/`target` are added by transformTags but were dropped
    // again because the allowlist did not name them — the transform runs
    // first, the attribute allowlist filters after.
    const html = renderMarkdown('[docs](https://docs.rsmm.me/)');
    expect(html).toContain('href="https://docs.rsmm.me/"');
    expect(html).toContain('rel="nofollow ugc noopener noreferrer"');
    expect(html).toContain('target="_blank"');
  });

  it('lazy-loads description images', () => {
    const html = renderMarkdown('![shot](https://cdn.rsmm.me/a.png)');
    expect(html).toContain('loading="lazy"');
    expect(html).toContain('decoding="async"');
  });

  it('returns empty string for empty input, so callers can test the result', () => {
    expect(renderMarkdown(null)).toBe('');
    expect(renderMarkdown(undefined)).toBe('');
    expect(renderMarkdown('   \n  ')).toBe('');
  });
});

describe('markdownToText', () => {
  it('reduces Markdown to a single collapsed line of words', () => {
    expect(markdownToText('## Title\n\n- one\n- two')).toBe('Title one two');
  });

  it('drops markup entirely rather than escaping it', () => {
    expect(markdownToText('<script>alert(1)</script>hello')).toBe('hello');
  });

  it('truncates on the limit with an ellipsis', () => {
    const out = markdownToText('x'.repeat(500), 20);
    expect(out).toHaveLength(20);
    expect(out.endsWith('…')).toBe(true);
  });
});
