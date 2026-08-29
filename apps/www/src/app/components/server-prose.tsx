import { ArrowLeft } from 'lucide-react';
import type { Route } from 'next';
import Link from 'next/link';
import { renderMarkdown } from '../../lib/markdown';

/**
 * The server-rendered prose header for a content page.
 *
 * Every `[slug]` page under `/registry`, `/guides` and `/c` is a client
 * component that loads its record through react-query, so the HTML a crawler
 * receives held the nav and footer and nothing else — 586 visible characters,
 * byte-identical across all of them. The record is already fetched server-side
 * one level up (each `[slug]/layout.tsx` needs it for `generateMetadata` and
 * JSON-LD), so rendering the prose there costs no extra round-trip and is what
 * puts the page's actual words in the first-wave HTML.
 *
 * It renders in the layout, above `children`, which is why the title and body
 * now sit above the cover image rather than below it.
 *
 * `data-server-prose` is the hook the client page uses to hide this block while
 * an owner has the inline editor open — see `[data-editing='true']` in
 * globals.css. Without it an editing owner would see the saved copy stranded
 * above their own draft.
 */
export function ServerProse({
  backHref,
  backLabel,
  title,
  byline,
  summary,
  body,
  bodyHeading,
  bodyFallback,
  card = false,
  titleClassName = 'text-3xl font-bold tracking-tight',
  containerClassName = 'relative container mx-auto space-y-6 px-6 pt-12',
}: {
  backHref: Route | string;
  backLabel: string;
  title: string;
  byline?: string | null;
  summary?: string | null;
  /** Markdown. Sanitized here before it reaches the DOM. */
  body?: string | null;
  bodyHeading?: string;
  bodyFallback?: string | null;
  /** Wrap the body in the same `grimoire-card` the client page used. */
  card?: boolean;
  titleClassName?: string;
  /** Must match the client page's own container, or the two halves of the
   *  page render at different widths. */
  containerClassName?: string;
}) {
  const html = renderMarkdown(body);
  const fallback = bodyFallback?.trim();

  const bodyBlock =
    html || fallback ? (
      <>
        {bodyHeading ? (
          <h2 className="text-xl font-bold tracking-tight mb-4">{bodyHeading}</h2>
        ) : null}
        {html ? (
          <article
            data-color-mode="dark"
            className="md-editor-themed prose-invert max-w-none"
            // biome-ignore lint/security/noDangerouslySetInnerHtml: user-submitted Markdown, rendered and tag-allowlisted by renderMarkdown() — see lib/markdown.ts.
            dangerouslySetInnerHTML={{ __html: html }}
          />
        ) : (
          <p className="text-muted-foreground">{fallback}</p>
        )}
      </>
    ) : null;

  return (
    <div data-server-prose className={containerClassName}>
      <Link
        href={backHref as Route}
        className="inline-flex items-center rounded-md border border-input bg-background px-3 py-1.5 text-sm font-medium hover:bg-accent hover:text-accent-foreground"
      >
        <ArrowLeft className="mr-1.5 h-4 w-4" /> {backLabel}
      </Link>

      <header>
        <h1 className={titleClassName}>{title}</h1>
        {byline ? <p className="text-sm text-muted-foreground mt-1">{byline}</p> : null}
      </header>

      {summary?.trim() ? (
        <p className="text-lg text-muted-foreground max-w-3xl">{summary}</p>
      ) : null}

      {bodyBlock ? card ? <div className="grimoire-card p-6">{bodyBlock}</div> : bodyBlock : null}
    </div>
  );
}
