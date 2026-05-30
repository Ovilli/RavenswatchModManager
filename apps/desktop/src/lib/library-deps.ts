import { type activeProfile, getMod, isEnabledIn } from '../store';

type Profile = ReturnType<typeof activeProfile>;

/** How many of a mod's declared dependencies are absent from the profile's load order. */
export function getMissingDependencyCount(
  mod: NonNullable<ReturnType<typeof getMod>>,
  profile: Profile,
): number {
  return mod.dependencies.filter((depId) => !profile.loadOrder.includes(depId)).length;
}

/**
 * Compare two version strings segment by segment. Numeric segments compare
 * numerically; mixed numeric/alpha sorts numeric-after-alpha; a shorter
 * prefix sorts before its longer extension (1.0 < 1.0.1). Returns the usual
 * negative / 0 / positive ordering.
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

/**
 * Topologically order `ids` plus their transitive dependencies so each
 * dependency is enabled before the mod that needs it. Dependency ids with no
 * known mod are collected in `missing` rather than placed in `order`.
 */
export function buildEnablePlan(ids: string[]): { order: string[]; missing: string[] } {
  const seen = new Set<string>();
  const visiting = new Set<string>();
  const missing = new Set<string>();
  const order: string[] = [];

  const visit = (id: string) => {
    if (seen.has(id) || visiting.has(id)) return;
    visiting.add(id);
    const mod = getMod(id);
    if (!mod) {
      missing.add(id);
      visiting.delete(id);
      return;
    }
    for (const depId of mod.dependencies) visit(depId);
    visiting.delete(id);
    seen.add(id);
    order.push(id);
  };

  for (const id of ids) visit(id);
  return { order, missing: [...missing] };
}

/**
 * Find enabled mods that depend on any of `ids` — i.e. the mods that would
 * break if `ids` were disabled. Maps each target id to the names of its
 * enabled dependents.
 */
export function findBlockingDependents(ids: string[], profile: Profile) {
  const target = new Set(ids);
  const blocked = new Map<string, string[]>();

  for (const modId of profile.loadOrder) {
    if (!isEnabledIn(profile, modId) || target.has(modId)) continue;
    const mod = getMod(modId);
    if (!mod) continue;
    for (const depId of mod.dependencies) {
      if (!target.has(depId)) continue;
      const list = blocked.get(depId) ?? [];
      list.push(mod.name);
      blocked.set(depId, list);
    }
  }

  return [...blocked.entries()].map(([targetId, dependents]) => [targetId, dependents] as const);
}
