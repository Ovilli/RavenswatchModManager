import { describe, expect, it } from 'vitest';
import {
  IDLE_ACTION_COUNT,
  type PaletteAction,
  type PaletteHit,
  buildRows,
  matchesAction,
} from './palette';

function action(id: string, label: string, keywords = ''): PaletteAction {
  return { id, label, keywords, hint: 'action', run: () => undefined };
}

function hit(slug: string): PaletteHit {
  return { id: slug, slug, name: slug, author: 'someone', origin: 'library' };
}

const ACTIONS = [
  action('launch:modded', 'Launch Modded', 'play start game run mods'),
  action('launch:vanilla', 'Launch Vanilla', 'play start game unmodded'),
  action('restore', 'Restore original files', 'undo revert clean'),
  action('go:/settings', 'Settings', 'paths font size density'),
];

describe('matchesAction', () => {
  it('matches the visible label', () => {
    expect(matchesAction(ACTIONS[0] as PaletteAction, 'modded')).toBe(true);
  });

  it('matches hidden keywords so synonyms work', () => {
    expect(matchesAction(ACTIONS[2] as PaletteAction, 'revert')).toBe(true);
    expect(matchesAction(ACTIONS[3] as PaletteAction, 'font')).toBe(true);
  });

  it('rejects a miss', () => {
    expect(matchesAction(ACTIONS[3] as PaletteAction, 'zzz')).toBe(false);
  });
});

describe('buildRows', () => {
  it('offers only a few actions before anything is typed', () => {
    const rows = buildRows(ACTIONS, [hit('a'), hit('b')], '');
    expect(rows.filter((r) => r.kind === 'action')).toHaveLength(IDLE_ACTION_COUNT);
    expect(rows).toHaveLength(IDLE_ACTION_COUNT + 2);
  });

  it('ranks matching actions above mod hits so Enter hits the verb', () => {
    const rows = buildRows(ACTIONS, [hit('launcher-tweaks')], 'launch');
    expect(rows[0]?.kind).toBe('action');
    expect(rows.at(-1)?.kind).toBe('mod');
  });

  it('drops non-matching actions once a query narrows things', () => {
    const rows = buildRows(ACTIONS, [], 'settings');
    expect(rows).toHaveLength(1);
    expect(rows[0]).toMatchObject({ kind: 'action', action: { id: 'go:/settings' } });
  });

  it('ignores surrounding whitespace and case in the query', () => {
    expect(buildRows(ACTIONS, [], '  REVERT ')).toHaveLength(1);
  });

  it('returns mods alone when no action matches', () => {
    const rows = buildRows(ACTIONS, [hit('a')], 'zzz');
    expect(rows).toEqual([{ kind: 'mod', hit: hit('a') }]);
  });
});
