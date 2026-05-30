import { beforeEach, describe, expect, it } from 'vitest';
import { type Profile, useApp } from '../store';
import {
  buildEnablePlan,
  compareVersions,
  findBlockingDependents,
  getMissingDependencyCount,
} from './library-deps';
import type { LocalMod } from './rsmm';

function localMod(id: string, deps: string[] = []): LocalMod {
  return {
    id,
    slug: id,
    name: id,
    version: '1.0.0',
    author: null,
    summary: null,
    license: null,
    tags: [],
    enabled: true,
    path: `/mods/${id}`,
    dependencies: Object.fromEntries(deps.map((d) => [d, '*'])),
    writes: [],
  };
}

function profile(loadOrder: string[], disabled: string[] = []): Profile {
  return {
    id: 'p',
    name: 'p',
    loadOrder,
    disabled: new Set(disabled),
    createdAt: new Date().toISOString(),
  };
}

beforeEach(() => {
  useApp.setState({ localMods: {}, installed: [] });
});

describe('compareVersions', () => {
  it('orders numeric segments numerically, not lexically', () => {
    expect(compareVersions('1.2.0', '1.10.0')).toBeLessThan(0); // 2 < 10, beats string compare
    expect(compareVersions('1.10.0', '1.2.0')).toBeGreaterThan(0);
  });

  it('returns 0 for equal versions and orders a shorter prefix first', () => {
    expect(compareVersions('1.0.0', '1.0.0')).toBe(0);
    expect(compareVersions('1.0', '1.0.1')).toBeLessThan(0);
    expect(compareVersions('2.0.0', '1.9.9')).toBeGreaterThan(0);
  });
});

describe('buildEnablePlan', () => {
  it('orders dependencies before dependents', () => {
    useApp.getState().syncLocalMods([localMod('app', ['lib']), localMod('lib')]);
    const plan = buildEnablePlan(['app']);
    expect(plan.missing).toEqual([]);
    expect(plan.order.indexOf('lib')).toBeLessThan(plan.order.indexOf('app'));
  });

  it('collects unknown dependency ids as missing', () => {
    useApp.getState().syncLocalMods([localMod('app', ['ghost'])]);
    const plan = buildEnablePlan(['app']);
    expect(plan.missing).toEqual(['ghost']);
    expect(plan.order).toEqual(['app']);
  });

  it('terminates on a dependency cycle', () => {
    useApp.getState().syncLocalMods([localMod('a', ['b']), localMod('b', ['a'])]);
    const plan = buildEnablePlan(['a']);
    expect(plan.order.sort()).toEqual(['a', 'b']); // both included, no infinite loop
  });
});

describe('findBlockingDependents', () => {
  it('reports enabled mods that depend on a disable target', () => {
    useApp.getState().syncLocalMods([localMod('lib'), localMod('consumer', ['lib'])]);
    const blocked = findBlockingDependents(['lib'], profile(['lib', 'consumer']));
    expect(blocked).toEqual([['lib', ['consumer']]]);
  });

  it('ignores disabled dependents and the targets themselves', () => {
    useApp.getState().syncLocalMods([localMod('lib'), localMod('consumer', ['lib'])]);
    // consumer is disabled → it no longer blocks disabling lib.
    const blocked = findBlockingDependents(['lib'], profile(['lib', 'consumer'], ['consumer']));
    expect(blocked).toEqual([]);
  });
});

describe('getMissingDependencyCount', () => {
  it('counts dependencies absent from the profile load order', () => {
    useApp.getState().syncLocalMods([localMod('app', ['x', 'y'])]);
    const mod = useApp.getState().localMods.app;
    if (!mod) throw new Error('mod not synced');
    expect(getMissingDependencyCount(mod, profile(['app', 'x']))).toBe(1); // y missing
    expect(getMissingDependencyCount(mod, profile(['app', 'x', 'y']))).toBe(0);
  });
});
