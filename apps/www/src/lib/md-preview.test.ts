import MDEditor from '@uiw/react-md-editor';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import { isSafeUrl, rehypeSafeHtml } from './md-preview';

// Rendered through the real library, not a hand-built tree: the bug was that
// `@uiw/react-md-editor` always runs `rehype-raw`, so what matters is what the
// component emits with the plugin in the slot the site passes it in.
const render = (source: string, safe = true) =>
  renderToStaticMarkup(
    createElement(MDEditor.Markdown, {
      source,
      ...(safe ? { rehypePlugins: [rehypeSafeHtml] } : {}),
    }),
  );

const SRCDOC = '<iframe srcdoc="<script>parent.alert(document.domain)</script>"></iframe>';

describe('rehypeSafeHtml', () => {
  it('the unprotected component really does emit a scriptable srcdoc frame', () => {
    // Guards the premise: if the library ever stops rendering raw HTML this
    // test says so, rather than the one below passing for the wrong reason.
    expect(render(SRCDOC, false)).toContain('srcDoc=');
  });

  it('drops the srcdoc iframe and its payload', () => {
    const html = render(`hello\n\n${SRCDOC}`);
    expect(html).not.toMatch(/iframe|srcdoc|script/i);
    expect(html).toContain('hello');
  });

  it('drops attributes the rehype-attr comment syntax adds', () => {
    const html = render('para\n<!--rehype:style=position:fixed&srcdoc=x-->');
    expect(html).not.toMatch(/style=|srcdoc/i);
  });

  it('removes executable and embedding elements, unwraps unknown ones', () => {
    const html = render(
      '<object data="x"></object><embed src="x"><form><button formaction="x">b</button></form><center>kept</center>',
    );
    expect(html).not.toMatch(/<object|<embed|<form|<button|formaction/i);
    expect(html).toContain('kept');
  });

  it('keeps ordinary Markdown', () => {
    const html = render(
      '# Title\n\n**bold** [link](https://rsmm.me/x) ![i](https://cdn.rsmm.me/a.png)\n\n- [x] done\n\n| a |\n|---|\n| b |',
    );
    expect(html).toContain('<strong>bold</strong>');
    expect(html).toContain('href="https://rsmm.me/x"');
    expect(html).toContain('src="https://cdn.rsmm.me/a.png"');
    expect(html).toContain('<table>');
    expect(html).toMatch(/<input[^>]*type="checkbox"/);
  });

  it('strips unsafe URLs from raw HTML links and images', () => {
    const html = render('<a href="data:text/html,x">a</a><img src="//evil.example/x.png">');
    expect(html).not.toMatch(/data:text|evil\.example/);
  });
});

describe('isSafeUrl', () => {
  it.each([
    ['https://rsmm.me', true],
    ['http://x.y', true],
    ['mailto:a@b.c', true],
    ['#frag', true],
    ['/registry/x', true],
    ['//evil.example', false],
    ['/\\evil.example', false],
    ['javascript:alert(1)', false],
    [' data:text/html,x', false],
    ['vbscript:x', false],
  ])('%s → %s', (url, ok) => {
    expect(isSafeUrl(url)).toBe(ok);
  });
});
