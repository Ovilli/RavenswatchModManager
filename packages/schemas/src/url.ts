import { z } from 'zod';

/**
 * A URL that is safe to put in an `href`, `src`, or `<img>` on a page we serve.
 *
 * `z.string().url()` only asks whether `new URL()` parses the string — so
 * `javascript:alert(document.cookie)`, `data:text/html;base64,…`, `vbscript:`
 * and `file:///etc/passwd` all pass it. Every user-supplied link on the site
 * (mod repo/homepage/cover image/screenshots/videos, guide and collection
 * images) was validated with the bare `.url()`, which means a publisher could
 * store a `javascript:` URL that the registry then rendered into an anchor —
 * stored XSS, one publish away, with the scheme never once inspected.
 *
 * The allowlist is deliberately just http/https: those are the only schemes
 * anything on the site needs to render, and an allowlist is the only form of
 * this check that stays correct as browsers add schemes.
 */
export const HTTP_URL_MAX = 2048;

const ALLOWED_PROTOCOLS = new Set(['http:', 'https:']);

export const httpUrlSchema = z
  .string()
  .max(HTTP_URL_MAX, 'url is too long')
  .url()
  .refine(
    (value) => {
      try {
        return ALLOWED_PROTOCOLS.has(new URL(value).protocol);
      } catch {
        return false;
      }
    },
    { message: 'url must use http or https' },
  );

/**
 * Render-side companion to `httpUrlSchema`, for values that were stored before
 * the schema existed. Validation at the edge cannot retroactively clean rows
 * already in the database, so display code that turns a stored value into an
 * `href`/`src` runs it through this and drops anything that is not http(s).
 */
export function safeHttpUrl(value: string | null | undefined): string | null {
  if (!value) return null;
  if (value.length > HTTP_URL_MAX) return null;
  try {
    return ALLOWED_PROTOCOLS.has(new URL(value).protocol) ? value : null;
  } catch {
    return null;
  }
}

/**
 * Response-shape counterpart to `httpUrlSchema`: sanitizes instead of rejecting.
 *
 * The response schemas are parsed at runtime by `@rsmm/api-client`, so making
 * them strict would mean one legacy row holding a `javascript:` image URL fails
 * the whole `z.array(modListItemSchema)` and blanks the entire registry page —
 * turning a stored-XSS payload into a site-wide denial of service. Nulling the
 * single offending field instead keeps the page up and still guarantees no
 * non-http(s) URL ever reaches a renderer.
 */
export const sanitizedHttpUrlSchema = z
  .string()
  .transform((v) => safeHttpUrl(v))
  .nullish();

/**
 * Sanitize-don't-reject for an OPTIONAL field. Used by `modManifestSchema`,
 * which is both an upload-time input gate and part of the mod-detail response
 * shape: rejecting there would let one legacy manifest 404 a whole mod page,
 * while silently dropping the unsafe value still guarantees it is never stored
 * and never rendered.
 */
export const sanitizedOptionalHttpUrlSchema = z
  .string()
  .transform((v) => safeHttpUrl(v) ?? undefined)
  .optional();

/** Same sanitize-don't-reject rule for a list of URLs: unsafe entries drop out. */
export const sanitizedHttpUrlArraySchema = z
  .array(z.string())
  .transform((list) => list.map(safeHttpUrl).filter((u): u is string => u !== null))
  .optional();
