/**
 * Allowlist sanitizer for the CLIENT-side Markdown renderer.
 *
 * `@uiw/react-md-editor` (its `Markdown` preview and the editor's own preview
 * pane) always runs `rehype-raw`, so raw HTML in user Markdown becomes real
 * elements. React neutralises `on*` string handlers and `javascript:` URLs, but
 * not `<iframe srcdoc="<script>…">`: a srcdoc frame is same-origin with the page
 * and inherits this site's `script-src 'unsafe-inline'`, so a mod changelog or a
 * guide body ran script as rsmm.me for every signed-in visitor (and for the
 * admin reviewing it). `lib/markdown.ts` sanitizes the server-rendered prose;
 * this is the same rule for the client renderer.
 *
 * It is a rehype plugin passed through the component's `rehypePlugins` prop,
 * which the library appends AFTER `rehype-raw` and `rehype-attr` (the
 * `<!--rehype:…-->` comment syntax that adds attributes), so nothing that runs
 * before it can smuggle an element or attribute past it. Dependency-free on
 * purpose: `rehype-sanitize` is not installed, and a tree walk is all it takes.
 */

interface HastNode {
  type: string;
  tagName?: string;
  properties?: Record<string, unknown>;
  children?: HastNode[];
}

/** Elements Markdown (GFM + the preview's alerts, footnotes, heading anchors
 *  and copy buttons) produces. */
const ALLOWED_TAGS = new Set([
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
  's',
  'hr',
  'br',
  'img',
  'table',
  'thead',
  'tbody',
  'tr',
  'th',
  'td',
  'input',
  'sup',
  'sub',
  'section',
  'span',
  'div',
  'kbd',
  'details',
  'summary',
  'svg',
  'path',
]);

/** Elements removed WITH their content. Any other unknown element is unwrapped
 *  (its children are kept and re-checked), so prose inside e.g. `<center>`
 *  survives while the element itself and all its attributes do not. */
const DROP_WITH_CONTENT = new Set([
  'script',
  'style',
  'iframe',
  'frame',
  'frameset',
  'object',
  'embed',
  'template',
  'noscript',
  'noembed',
  'textarea',
  'title',
  'xmp',
  'select',
  'math',
]);

/** hast property names (camelCase) that carry no behaviour. */
const ALLOWED_PROPS = new Set([
  'href',
  'src',
  'alt',
  'title',
  'className',
  'id',
  'align',
  'colSpan',
  'rowSpan',
  'start',
  'type',
  'checked',
  'disabled',
  'open',
  'viewBox',
  'width',
  'height',
  'd',
  'fill',
  'fillRule',
  'clipRule',
  'version',
  'dataCode',
  'dataFootnotes',
  'dataFootnoteRef',
  'dataFootnoteBackref',
]);

const URL_PROPS = new Set(['href', 'src']);

/** http(s), mailto, a fragment, or a path on this site. No other scheme and no
 *  protocol-relative `//host`. */
export function isSafeUrl(value: string): boolean {
  const v = value.trim();
  if (/^(?:https?:|mailto:)/i.test(v)) return true;
  if (v.startsWith('#')) return true;
  return v.startsWith('/') && !v.startsWith('//') && !v.startsWith('/\\');
}

function cleanProps(tag: string, props: Record<string, unknown>): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(props)) {
    if (!(ALLOWED_PROPS.has(key) || key.startsWith('aria'))) continue;
    if (URL_PROPS.has(key)) {
      if (typeof value !== 'string' || !isSafeUrl(value)) continue;
    }
    out[key] = value;
  }
  // A checkbox is the only input GFM emits (task lists); it is always inert.
  if (tag === 'input') return out.type === 'checkbox' ? { ...out, disabled: true } : {};
  return out;
}

function sanitizeChildren(children: HastNode[]): HastNode[] {
  const out: HastNode[] = [];
  for (const child of children) {
    if (child.type === 'text') {
      out.push(child);
      continue;
    }
    if (child.type !== 'element' || !child.tagName) continue; // comment, raw, doctype
    const tag = child.tagName.toLowerCase();
    if (DROP_WITH_CONTENT.has(tag)) continue;
    const kids = sanitizeChildren(child.children ?? []);
    if (!ALLOWED_TAGS.has(tag)) {
      out.push(...kids);
      continue;
    }
    out.push({
      ...child,
      tagName: tag,
      properties: cleanProps(tag, child.properties ?? {}),
      children: kids,
    });
  }
  return out;
}

/** Sanitize a hast tree in place. Exported for tests. */
export function sanitizeHast<T extends HastNode>(tree: T): T {
  tree.children = sanitizeChildren(tree.children ?? []);
  return tree;
}

/** The rehype plugin: `rehypePlugins={[rehypeSafeHtml]}`. */
export function rehypeSafeHtml() {
  return (tree: HastNode) => {
    sanitizeHast(tree);
  };
}
