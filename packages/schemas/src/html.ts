/**
 * Safe serializer for inline `<script type="application/ld+json">` bodies.
 *
 * `JSON.stringify` escapes quotes and backslashes but NOT `<`, `>` or `&` —
 * and an inline `<script>` body is read by the HTML tokenizer *before* any
 * JSON parser sees it. So a mod named
 *
 *     Cool Mod</script><img src=x onerror=alert(document.cookie)>
 *
 * closes the script element and injects live markup into rsmm.me. Every field
 * that reaches a JSON-LD block (mod name/summary/author, guide title/summary,
 * collection name) is user-submitted through the publish API, so this is a
 * stored-XSS sink — not "our own data" as the call sites used to claim.
 *
 * Escaping `<`/`>` keeps the JSON semantically identical (every consumer
 * unescapes it) while making the byte sequence `</script` unwritable. `&` is
 * escaped so the payload also survives any HTML-entity decoding context, and
 * U+2028/U+2029 because they are literal line terminators to a JavaScript
 * parser yet legal raw inside a JSON string.
 *
 * The last two patterns are written as \u escapes rather than as the raw
 * characters on purpose: pasted literally into a regex they terminate the
 * literal early and the file stops compiling — the same class of bug, one
 * layer down.
 */
export function jsonLd(value: unknown): string {
  return JSON.stringify(value)
    .replace(/</g, '\\u003c')
    .replace(/>/g, '\\u003e')
    .replace(/&/g, '\\u0026')
    .replace(/\u2028/g, '\\u2028')
    .replace(/\u2029/g, '\\u2029');
}
