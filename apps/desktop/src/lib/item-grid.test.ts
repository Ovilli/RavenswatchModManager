import { describe, expect, it } from 'vitest';
import {
  candidates,
  defaultItems,
  groupSections,
  numberEditable,
  optionNumber,
  sectionCount,
  sectionItems,
  withCount,
  withItems,
  withNumber,
  withSectionReset,
} from './item-grid';
import type { ItemGridSpec, ModConfigChoice } from './rsmm';

// A made-up grid: nothing about it is any real mod's. The logic must not care.
const spec: ItemGridSpec = {
  sections: [
    {
      id: 'left',
      label: 'Left',
      group: 'Hands',
      accepts: { kind: 'tool' },
      count: { label: 'Carried', min: 1, max: 3, default: 2 },
    },
    { id: 'right', label: 'Right', group: 'Hands', accepts: { kind: 'tool' }, count: null },
    { id: 'pack', label: 'Pack', group: '', accepts: { kind: 'food' }, count: null },
  ],
  number: { attr: 'cost', label: 'Cost', min: 0, max: 50, editable: 'canEdit' },
  themeSlots: [],
  themeInk: {},
  title: '',
  quote: '',
  layout: 'stack',
};

const opt = (id: string, attrs: ModConfigChoice['attrs']): ModConfigChoice => ({
  id,
  label: id,
  group: '',
  icon: '',
  description: '',
  attrs,
});

const options = [
  opt('axe', { kind: 'tool', cost: 10, canEdit: true, defaultIn: ['left'] }),
  opt('saw', { kind: 'tool', cost: 20, canEdit: true, defaultIn: ['left', 'right'] }),
  opt('rope', { kind: 'tool', cost: 5, canEdit: false, defaultIn: [] }),
  opt('bread', { kind: 'food', cost: 1, canEdit: true, defaultIn: ['pack'] }),
];
const [left, right, pack] = spec.sections as [
  (typeof spec.sections)[0],
  (typeof spec.sections)[0],
  (typeof spec.sections)[0],
];

describe('item-grid defaults', () => {
  it('come from the provider, filtered by what the section accepts', () => {
    expect(defaultItems(left, options)).toEqual(['axe', 'saw']);
    expect(defaultItems(right, options)).toEqual(['saw']);
    expect(defaultItems(pack, options)).toEqual(['bread']);
    expect(sectionItems({}, left, options)).toEqual(['axe', 'saw']);
    expect(sectionCount({}, left)).toBe(2);
    expect(sectionCount({}, right)).toBeNull();
  });

  it('offers only accepted options that are not already in the section', () => {
    expect(candidates({}, left, options).map((o) => o.id)).toEqual(['rope']);
    expect(candidates({}, pack, options)).toEqual([]);
  });

  it('groups consecutive sections', () => {
    expect(groupSections(spec).map((g) => [g.group, g.sections.map((s) => s.id)])).toEqual([
      ['Hands', ['left', 'right']],
      ['', ['pack']],
    ]);
  });
});

describe('item-grid edits store only what differs', () => {
  it('drops a section edited back to its defaults', () => {
    const added = withItems(spec, {}, options, 'left', ['axe', 'saw', 'rope']);
    expect(added).toEqual({ sections: { left: { items: ['axe', 'rope', 'saw'] } } });
    const back = withItems(spec, added, options, 'left', ['saw', 'axe']);
    expect(back).toEqual({});
  });

  it('never empties a section or drops it below its minimum count', () => {
    expect(withItems(spec, {}, options, 'right', [])).toEqual({});
    // `left` must offer at least 1 (its count.min), so one item is still allowed…
    const one = withItems(spec, {}, options, 'left', ['axe']);
    expect(one.sections?.left).toEqual({ items: ['axe'], count: 1 });
    // …but a section whose minimum is 2 keeps at least two.
    const strict = {
      ...spec,
      sections: spec.sections.map((s) =>
        s.id === 'left' && s.count ? { ...s, count: { ...s.count, min: 2 } } : s,
      ),
    };
    expect(withItems(strict, {}, options, 'left', ['axe'])).toEqual({});
  });

  it('clamps counts and numbers to the declaration', () => {
    expect(withCount(spec, {}, options, left, 9)).toEqual({ sections: { left: { count: 3 } } });
    expect(withCount(spec, {}, options, left, 2)).toEqual({});
    expect(withNumber(spec, {}, options, 'axe', 99)).toEqual({ numbers: { axe: 50 } });
    expect(withNumber(spec, {}, options, 'axe', 10)).toEqual({});
  });

  it('ignores numbers on options whose number is not editable', () => {
    expect(numberEditable(spec, options[2] as ModConfigChoice)).toBe(false);
    expect(withNumber(spec, {}, options, 'rope', 3)).toEqual({});
    expect(optionNumber(spec, {}, options[2] as ModConfigChoice)).toBe(5);
  });

  it('restores one section without touching the rest', () => {
    const edited = withNumber(
      spec,
      withItems(spec, {}, options, 'left', ['rope']),
      options,
      'bread',
      4,
    );
    expect(withSectionReset(spec, edited, options, left)).toEqual({ numbers: { bread: 4 } });
  });
});
