import { marked } from 'marked';
import sanitizeHtml from 'sanitize-html';

/**
 * Server-side Markdown renderer for user-submitted prose.
 *
 * Mod descriptions, guide bodies and collection descriptions used to reach the
 * page only through `@uiw/react-md-editor`'s `Markdown` component, which is
 * loaded with `ssr: false`. That meant the rendered HTML for every content page
 * carried the nav and footer and nothing else — 586 visible characters,
 * identical on `/registry`, `/guides` and every `[slug]` under them. Google's
 * first indexing wave sees exactly that shell, and a shell with no page-specific
 * text routinely never comes back for the render pass. Server-rendering the
 * prose is what makes those pages indexable at all.
 *
 * The output is fed to `dangerouslySetInnerHTML`, so it is sanitized here rather
 * than trusted: the input is arbitrary Markdown typed by any registered user,
 * and Markdown permits raw HTML by construction. `marked` does not sanitize (it
 * dropped its own `sanitize` option precisely so callers would use a real
 * sanitizer), so the two steps are not interchangeable and neither is optional.
 */

// Allow the tags Markdown actually produces, and nothing else. No `<script>`,
// no `<style>`, no `<iframe>`, no form elements — a description is prose, and
// anything that can execute or collect input has no business in one.
const ALLOWED_TAGS = [
  'h1',
  'h2',
  'h3',
  'h4',
  'h5',
  'h6',
  'p',
  'a',
  'ul',
  'ol',
  'li',
  'blockquote',
  'code',
  'pre',
  'em',
  'strong',
  'del',
  'hr',
  'br',
  'img',
  'table',
  'thead',
  'tbody',
  'tr',
  'th',
  'td',
];

/**
 * Render Markdown to sanitized HTML.
 *
 * Returns an empty string for empty input so a caller can use the result itself
 * as the "is there prose here" test.
 */
export function renderMarkdown(source: string | null | undefined): string {
  const src = source?.trim();
  if (!src) return '';

  // `async: false` pins the synchronous overload — `marked.parse` is typed
  // `string | Promise<string>` otherwise, and this runs inside a synchronous
  // server component.
  const html = marked.parse(src, { async: false, gfm: true, breaks: true });

  return sanitizeHtml(html, {
    allowedTags: ALLOWED_TAGS,
    allowedAttributes: {
      // `rel`/`target` and `loading`/`decoding` are added by transformTags
      // below, and an attribute the transform adds is still dropped unless it
      // is allowed here — the transform runs first, the allowlist filters after.
      a: ['href', 'title', 'rel', 'target'],
      img: ['src', 'alt', 'title', 'loading', 'decoding'],
      // GFM alignment on table cells is the one style-ish attribute worth
      // keeping; it is an enum, not free-form CSS.
      th: ['align'],
      td: ['align'],
    },
    // No `data:` — a data: URI is how an image attribute smuggles a payload.
    allowedSchemes: ['http', 'https', 'mailto'],
    // A relative `href` cannot be resolved against a host here, and a
    // protocol-relative one silently inherits the page's scheme.
    allowProtocolRelative: false,
    // Untrusted outbound links: deny referrer and opener, and tell search
    // engines this is not an endorsement.
    transformTags: {
      // Demote every heading one level. The page's own <h1> is the mod or
      // guide title; an author who opens their description with `# Title`
      // would otherwise put a second <h1> on it, which is exactly the signal
      // server-rendering this prose was meant to clean up. Each mapping is
      // applied to the ORIGINAL tag name, so this shifts the whole scale once
      // rather than cascading h1 all the way down to h6.
      h1: 'h2',
      h2: 'h3',
      h3: 'h4',
      h4: 'h5',
      h5: 'h6',
      h6: 'h6',
      a: sanitizeHtml.simpleTransform('a', {
        rel: 'nofollow ugc noopener noreferrer',
        target: '_blank',
      }),
      // Descriptions can reference large remote images; never let one block
      // first paint or push layout around after it.
      img: sanitizeHtml.simpleTransform('img', { loading: 'lazy', decoding: 'async' }),
    },
  });
}

/**
 * Plain-text reduction of Markdown, for places that need words without markup
 * (the summary fallback, mostly). Collapses whitespace so the result is a
 * single readable paragraph rather than the source's line breaks.
 */
export function markdownToText(source: string | null | undefined, limit = 400): string {
  const html = renderMarkdown(source);
  if (!html) return '';
  const text = sanitizeHtml(html, { allowedTags: [], allowedAttributes: {} })
    .replace(/\s+/g, ' ')
    .trim();
  return text.length > limit ? `${text.slice(0, limit - 1).trimEnd()}…` : text;
}
