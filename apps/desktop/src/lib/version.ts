/**
 * Compare two version strings segment by segment. Numeric segments compare
 * numerically; mixed numeric/alpha sorts numeric-after-alpha; a shorter
 * prefix sorts before its longer extension (1.0 < 1.0.1). Returns the usual
 * negative / 0 / positive ordering.
 *
 * Lives outside library-deps so the store can import it without a cycle
 * (library-deps itself imports from the store).
 */
export function compareVersions(a: string, b: string): number {
  const parse = (value: string) =>
    value
      .split(/[^0-9A-Za-z]+/)
      .filter(Boolean)
      .map((part) => {
        const numeric = Number(part);
        return Number.isNaN(numeric) ? part.toLowerCase() : numeric;
      });
  const left = parse(a);
  const right = parse(b);
  const len = Math.max(left.length, right.length);
  for (let i = 0; i < len; i += 1) {
    const l = left[i];
    const r = right[i];
    if (l === undefined) return -1;
    if (r === undefined) return 1;
    if (typeof l === 'number' && typeof r === 'number' && l !== r) return l - r;
    if (typeof l === 'number' && typeof r === 'string') return 1;
    if (typeof l === 'string' && typeof r === 'number') return -1;
    if (l !== r) return String(l).localeCompare(String(r));
  }
  return 0;
}
