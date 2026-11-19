/** Fictional fixtures for the development-only Library preview. */
import { type Profile, useApp } from '../store';
import type { LocalMod, ModConfigField, ModConfigResponse, ModConfigValue } from '../lib/rsmm';

type Fixture = Pick<LocalMod, 'id' | 'name' | 'summary' | 'tags'> &
  Partial<LocalMod> & {
    latestVersion?: string;
  };

const fixtures: Fixture[] = [
  {
    id: 'ravens-toolkit',
    name: 'Raven’s Toolkit',
    summary: 'Shared utilities for configurable mods, hero tweaks, and custom encounters.',
    tags: ['utility'],
    version: '2.4.0',
  },
  {
    id: 'expanded-talents',
    name: 'Expanded Talents',
    summary: 'New talent combinations and alternate upgrade paths for every hero.',
    tags: ['gameplay'],
    version: '1.3.0',
    latestVersion: '1.4.2',
    hasConfig: true,
    dependencies: { 'ravens-toolkit': '>=2.0' },
  },
  {
    id: 'scarlet-reimagined',
    name: 'Scarlet Reimagined',
    summary: 'A fresh take on Scarlet’s day and night forms, with new combat rhythms.',
    tags: ['gameplay'],
    hasConfig: true,
  },
  {
    id: 'nightmare-plus',
    name: 'Nightmare+',
    summary: 'Denser encounters, tougher elites, and a little less room for mistakes.',
    tags: ['difficulty'],
    version: '3.1.0',
    hasConfig: true,
  },
  {
    id: 'hyper-aggro',
    name: 'Hyper Aggro',
    summary: 'Enemies notice you sooner and pursue your party across the battlefield.',
    tags: ['difficulty'],
    enabled: false,
  },
  {
    id: 'clearer-hud',
    name: 'Clearer HUD',
    summary: 'Larger cooldown numbers and clearer status effects in the heat of battle.',
    tags: ['qol'],
    version: '1.2.1',
    hasConfig: true,
  },
  {
    id: 'quick-loot',
    name: 'Quick Loot',
    summary: 'Spend less time picking things up and more time fighting through Reverie.',
    tags: ['qol'],
    hasConfig: true,
  },
  {
    id: 'team-health-bars',
    name: 'Team Health Bars',
    summary: 'Keep track of your friends with persistent party health and shield bars.',
    tags: ['qol'],
    enabled: false,
  },
  {
    id: 'moonlit-cloaks',
    name: 'Moonlit Cloaks',
    summary: 'Cool silver and midnight blue outfits for the heroes of Reverie.',
    tags: ['cosmetic'],
    writes: ['heroes/scarlet/cloak.texture'],
  },
  {
    id: 'crimson-scarlet',
    name: 'Crimson Scarlet',
    summary: 'A deep crimson cloak with subtle embroidered details for Scarlet.',
    tags: ['cosmetic'],
    writes: ['heroes/scarlet/cloak.texture'],
  },
  {
    id: 'balanced-dreams',
    name: 'Balanced Dreams',
    summary: 'Gentle adjustments to underused talents and magical objects.',
    tags: ['balance'],
    version: '0.9.0',
    latestVersion: '1.0.0',
    enabled: false,
  },
  {
    id: 'generous-wishing-well',
    name: 'Generous Wishing Well',
    summary: 'More rewards from wishing wells, with a configurable price to match.',
    tags: ['balance'],
    hasConfig: true,
  },
  {
    id: 'reverie-soundscape',
    name: 'Reverie Soundscape',
    summary: 'Alternate ambient music for quieter moments between encounters.',
    tags: ['audio'],
  },
  {
    id: 'boss-rush',
    name: 'Boss Rush',
    summary: 'Face the nightmares back to back in a dedicated challenge run.',
    tags: ['gameplay'],
    dependencies: { 'encounter-framework': '>=1.0' },
    enabled: false,
  },
  {
    id: 'split-timer',
    name: 'Split Timer',
    summary: 'Track chapter times and compare your current run with a personal best.',
    tags: ['speedrun'],
    hasConfig: true,
  },
  {
    id: 'practice-room',
    name: 'Practice Room',
    summary: 'Try builds, practice attack patterns, and reset encounters on demand.',
    tags: ['utility'],
    enabled: false,
  },
];

function buildCatalog(): LocalMod[] {
  return fixtures.map((fixture) => ({
    slug: fixture.id,
    version: '1.0.0',
    author: 'Preview author',
    license: 'MIT',
    enabled: true,
    path: `/preview/mods/${fixture.id}`,
    dependencies: {},
    writes: [],
    ...fixture,
  }));
}

const folders = new Map<string, LocalMod[]>();
const configs = new Map<string, Record<string, ModConfigValue>>();

function profile(id: string, name: string, mods: LocalMod[]): Profile {
  folders.set(id, structuredClone(mods));
  return {
    id,
    name,
    loadOrder: mods.map((mod) => mod.id),
    disabled: new Set(mods.filter((mod) => !mod.enabled).map((mod) => mod.id)),
    createdAt: '2026-11-01T12:00:00.000Z',
  };
}

export function initializeLibraryPreview(): void {
  folders.clear();
  configs.clear();
  const catalog = buildCatalog();
  useApp.setState({
    profiles: [
      profile('default', 'My mods', catalog),
      profile(
        'coop',
        'Co-op nights',
        catalog.filter((mod) =>
          [
            'ravens-toolkit',
            'clearer-hud',
            'quick-loot',
            'team-health-bars',
            'moonlit-cloaks',
          ].includes(mod.id),
        ),
      ),
      profile(
        'challenge',
        'Nightmare runs',
        catalog.filter((mod) =>
          ['ravens-toolkit', 'nightmare-plus', 'hyper-aggro', 'split-timer'].includes(mod.id),
        ),
      ),
      profile('empty', 'Fresh start', []),
    ],
    activeProfileId: 'default',
    settings: { ...useApp.getState().settings, crashReports: false, usageReports: false },
  });
  previewCommand(['list']);
}

function configFor(modId: string, profileId: string): ModConfigResponse {
  const mod = (folders.get(profileId) ?? []).find((item) => item.id === modId);
  const fields: Record<string, ModConfigField> = mod?.hasConfig
    ? {
        intensity: {
          type: 'float',
          label: 'Effect strength',
          default: 1,
          min: 0.5,
          max: 3,
          choices: [],
        },
        notifications: {
          type: 'bool',
          label: 'Show in-game notifications',
          default: true,
          min: null,
          max: null,
          choices: [],
        },
        preset: {
          type: 'enum',
          label: 'Preset',
          default: 'balanced',
          min: null,
          max: null,
          choices: ['subtle', 'balanced', 'dramatic'],
        },
      }
    : {};
  return {
    ok: true,
    modId,
    schema: { fields },
    values:
      configs.get(`${profileId}:${modId}`) ??
      Object.fromEntries(
        Object.entries(fields).map(([key, field]) => [key, field.default as ModConfigValue]),
      ),
  };
}

export function copyPreviewProfile(sourceId: string, targetId: string): void {
  folders.set(targetId, structuredClone(folders.get(sourceId) ?? []));
  for (const [key, value] of configs) {
    if (key.startsWith(`${sourceId}:`))
      configs.set(key.replace(`${sourceId}:`, `${targetId}:`), structuredClone(value));
  }
}

/** Commands stay entirely in memory; unsupported actions never reach the CLI. */
export function previewCommand(
  args: string[],
  profileId = useApp.getState().activeProfileId,
): unknown {
  const [command, target = '', value = '', payload = '{}'] = args;
  switch (command) {
    case 'list': {
      const mods = structuredClone(folders.get(profileId) ?? []);
      useApp.getState().syncLocalMods(mods, profileId);
      if (profileId === useApp.getState().activeProfileId) {
        useApp
          .getState()
          .patchRemoteInfo(
            Object.fromEntries(
              fixtures.map((mod) => [
                mod.id,
                { latestVersion: mod.latestVersion ?? mod.version ?? '1.0.0' },
              ]),
            ),
          );
      }
      return mods;
    }
    case 'list-profiles':
      return {
        profiles: Object.fromEntries(
          args
            .slice(1)
            .map((id) => [id, { ok: true, mods: structuredClone(folders.get(id) ?? []) }]),
        ),
      };
    case 'config': {
      if (target === 'set') configs.set(`${profileId}:${value}`, JSON.parse(payload));
      return configFor(value, profileId);
    }
    case 'uninstall-mod':
      folders.set(
        profileId,
        (folders.get(profileId) ?? []).filter((mod) => mod.id !== target),
      );
      return { ok: true };
    case 'install-mod':
    case 'install-mod-version': {
      const fixture = buildCatalog().find((mod) => mod.slug === target);
      if (!fixture)
        return {
          ok: false,
          error:
            'This browser preview only installs sample mods. Reload to restore the sample library.',
        };
      const mod = {
        ...structuredClone(fixture),
        version:
          command === 'install-mod-version'
            ? value
            : (fixtures.find((item) => item.id === target)?.latestVersion ?? fixture.version),
      };
      folders.set(profileId, [
        ...(folders.get(profileId) ?? []).filter((item) => item.id !== mod.id),
        mod,
      ]);
      return { ok: true };
    }
    case 'overlays':
      return { gameDir: '/preview', overlays: [] };
    case 'game-status':
      return { running: false };
    case 'loader-health':
      return { exists: false, threshold: 3, canary: null, mods: [] };
    default:
      throw new Error(
        'This action requires the desktop app and is not simulated in the Library preview.',
      );
  }
}
