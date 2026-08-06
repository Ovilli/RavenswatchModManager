type Segment = string | number;

function parse(value: string): Segment[] {
  return value
    .split(/[^0-9A-Za-z]+/)
    .filter(Boolean)
    .map((part) => {
      const numeric = Number(part);
      return Number.isNaN(numeric) ? part.toLowerCase() : numeric;
    });
}

function compareSegments(left: Segment[], right: Segment[]): number {
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

/** Split `1.2.0-rc.1+build7` into its release core and prerelease tag.
 * Build metadata carries no precedence (semver §10), so it is dropped. */
function split(value: string): { base: string; pre: string } {
  const withoutBuild = value.split('+')[0] ?? '';
  const dash = withoutBuild.indexOf('-');
  return dash === -1
    ? { base: withoutBuild, pre: '' }
    : { base: withoutBuild.slice(0, dash), pre: withoutBuild.slice(dash + 1) };
}

/**
 * Compare two version strings segment by segment. Numeric segments compare
 * numerically; mixed numeric/alpha sorts numeric-after-alpha; a shorter
 * prefix sorts before its longer extension (1.0 < 1.0.1). Returns the usual
 * negative / 0 / positive ordering.
 *
 * A `-prerelease` tag ranks BELOW the release it qualifies (1.0.0-rc1 <
 * 1.0.0), per semver. Treating the tag as just another trailing segment made
 * it sort *above* the release, so anyone running a mod's beta was never told
 * the stable version was newer — the update badge stayed silent.
 *
 * Lives outside library-deps so the store can import it without a cycle
 * (library-deps itself imports from the store).
 */
export function compareVersions(a: string, b: string): number {
  const left = split(a);
  const right = split(b);
  const base = compareSegments(parse(left.base), parse(right.base));
  if (base !== 0) return base;
  if (!left.pre && !right.pre) return 0;
  if (!left.pre) return 1;
  if (!right.pre) return -1;
  return compareSegments(parse(left.pre), parse(right.pre));
}
