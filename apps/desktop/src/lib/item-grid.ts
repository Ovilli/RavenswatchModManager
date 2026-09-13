/**
 * Value logic for the generic `item-grid` config field, free of React so it
 * can be tested on its own. Nothing here knows what a grid is FOR — sections,
 * filters and the number all come from the mod's declaration (`ItemGridSpec`)
 * and the provider's options.
 *
 * A stored value keeps only what differs from the defaults: a section whose
 * items and count match them is dropped, and so is a number equal to the
 * option's own. An empty table therefore means "as the game ships", which is
 * what makes "Reset to defaults" a real reset and keeps the dirty check honest.
 */
import type { ItemGridSection, ItemGridSpec, ItemGridValue, ModConfigChoice } from './rsmm';

export function asGridValue(raw: unknown): ItemGridValue {
  return raw && typeof raw === 'object' && !Array.isArray(raw) ? (raw as ItemGridValue) : {};
}

/** Does `option` satisfy every attribute the section `accepts`? */
export function accepts(section: ItemGridSection, option: ModConfigChoice): boolean {
  return Object.entries(section.accepts).every(([k, v]) => option.attrs?.[k] === v);
}

export function defaultItems(section: ItemGridSection, options: ModConfigChoice[]): string[] {
  return options
    .filter((o) => {
      const inList = o.attrs?.defaultIn;
      return Array.isArray(inList) && inList.includes(section.id) && accepts(section, o);
    })
    .map((o) => o.id)
    .sort();
}

export function sectionItems(
  value: ItemGridValue,
  section: ItemGridSection,
  options: ModConfigChoice[],
): string[] {
  return value.sections?.[section.id]?.items ?? defaultItems(section, options);
}

/** The fewest items a section may hold: its minimum count, and never zero. */
export function minItems(section: ItemGridSection): number {
  return Math.max(1, section.count?.min ?? 1);
}

export function sectionCount(value: ItemGridValue, section: ItemGridSection): number | null {
  if (!section.count) return null;
  return value.sections?.[section.id]?.count ?? section.count.default;
}

export function defaultNumber(spec: ItemGridSpec, option: ModConfigChoice): number | null {
  if (!spec.number) return null;
  const raw = option.attrs?.[spec.number.attr];
  return typeof raw === 'number' ? raw : null;
}

export function numberEditable(spec: ItemGridSpec, option: ModConfigChoice): boolean {
  if (!spec.number) return false;
  return spec.number.editable == null || option.attrs?.[spec.number.editable] === true;
}

export function optionNumber(
  spec: ItemGridSpec,
  value: ItemGridValue,
  option: ModConfigChoice,
): number | null {
  return value.numbers?.[option.id] ?? defaultNumber(spec, option);
}

const sameIds = (a: string[], b: string[]) => {
  const x = [...a].sort();
  const y = [...b].sort();
  return x.length === y.length && x.every((v, i) => v === y[i]);
};

type Full = {
  sections: Record<string, { items: string[]; count: number | null }>;
  numbers: Record<string, number>;
};

function expand(spec: ItemGridSpec, value: ItemGridValue, options: ModConfigChoice[]): Full {
  const sections: Full['sections'] = {};
  for (const s of spec.sections) {
    sections[s.id] = { items: sectionItems(value, s, options), count: sectionCount(value, s) };
  }
  return { sections, numbers: { ...(value.numbers ?? {}) } };
}

/** Back to the stored form: stable key order, defaults dropped. */
function compact(spec: ItemGridSpec, full: Full, options: ModConfigChoice[]): ItemGridValue {
  const out: ItemGridValue = {};
  const sections: NonNullable<ItemGridValue['sections']> = {};
  for (const s of [...spec.sections].sort((a, b) => a.id.localeCompare(b.id))) {
    const cur = full.sections[s.id];
    if (!cur) continue;
    const entry: { items?: string[]; count?: number } = {};
    if (!sameIds(cur.items, defaultItems(s, options))) entry.items = [...new Set(cur.items)].sort();
    if (s.count && cur.count != null && cur.count !== s.count.default) entry.count = cur.count;
    if (entry.items || entry.count != null) sections[s.id] = entry;
  }
  if (Object.keys(sections).length) out.sections = sections;

  const byId = new Map(options.map((o) => [o.id, o]));
  const numbers: Record<string, number> = {};
  for (const id of Object.keys(full.numbers).sort()) {
    const opt = byId.get(id);
    const n = full.numbers[id];
    if (opt && n != null && numberEditable(spec, opt) && n !== defaultNumber(spec, opt)) {
      numbers[id] = n;
    }
  }
  if (Object.keys(numbers).length) out.numbers = numbers;
  return out;
}

export function withItems(
  spec: ItemGridSpec,
  value: ItemGridValue,
  options: ModConfigChoice[],
  sectionId: string,
  items: string[],
): ItemGridValue {
  const section = spec.sections.find((s) => s.id === sectionId);
  // A section cannot hold fewer items than it must offer (and never none): a
  // roll that comes up short can be fatal to the game, and the SDK refuses it.
  if (!section || items.length < minItems(section)) return value;
  const full = expand(spec, value, options);
  const cur = full.sections[sectionId];
  if (!cur) return value;
  const count =
    section.count && cur.count != null
      ? Math.max(section.count.min, Math.min(cur.count, items.length))
      : cur.count;
  full.sections[sectionId] = { items, count };
  return compact(spec, full, options);
}

export function withCount(
  spec: ItemGridSpec,
  value: ItemGridValue,
  options: ModConfigChoice[],
  section: ItemGridSection,
  count: number,
): ItemGridValue {
  if (!section.count) return value;
  const full = expand(spec, value, options);
  const cur = full.sections[section.id];
  if (!cur) return value;
  const clamped = Math.max(section.count.min, Math.min(section.count.max, Math.round(count)));
  full.sections[section.id] = { ...cur, count: clamped };
  return compact(spec, full, options);
}

export function withNumber(
  spec: ItemGridSpec,
  value: ItemGridValue,
  options: ModConfigChoice[],
  optionId: string,
  n: number,
): ItemGridValue {
  if (!spec.number || !Number.isFinite(n)) return value;
  const full = expand(spec, value, options);
  full.numbers[optionId] = Math.max(spec.number.min, Math.min(spec.number.max, Math.round(n)));
  return compact(spec, full, options);
}

export function withSectionReset(
  spec: ItemGridSpec,
  value: ItemGridValue,
  options: ModConfigChoice[],
  section: ItemGridSection,
): ItemGridValue {
  const full = expand(spec, value, options);
  full.sections[section.id] = {
    items: defaultItems(section, options),
    count: section.count?.default ?? null,
  };
  return compact(spec, full, options);
}

/** Options that could be added to `section`: accepted, not already in it. */
export function candidates(
  value: ItemGridValue,
  section: ItemGridSection,
  options: ModConfigChoice[],
): ModConfigChoice[] {
  const present = new Set(sectionItems(value, section, options));
  return options.filter((o) => accepts(section, o) && !present.has(o.id));
}

/** Consecutive sections sharing a `group`, in declaration order. */
export function groupSections(
  spec: ItemGridSpec,
): { group: string; sections: ItemGridSection[] }[] {
  const out: { group: string; sections: ItemGridSection[] }[] = [];
  for (const s of spec.sections) {
    const last = out[out.length - 1];
    if (last && last.group === s.group) last.sections.push(s);
    else out.push({ group: s.group, sections: [s] });
  }
  return out;
}
