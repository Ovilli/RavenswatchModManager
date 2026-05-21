import { create } from 'zustand';
import { persist, createJSONStorage } from 'zustand/middleware';
import { MOCK_MODS, type MockMod, type ModCategory } from '../data/mock-mods';
import type { LocalMod } from '../lib/rsmm';

export interface Profile {
  id: string;
  name: string;
  /** Installed mod IDs in load order. */
  loadOrder: string[];
  /** Mod IDs marked disabled inside this profile. */
  disabled: Set<string>;
  createdAt: string;
}

interface ProfileSerialized extends Omit<Profile, 'disabled'> {
  disabled: string[];
}

export interface AppSettings {
  gameDir: string;
  backupDir: string;
  /** Folder where mods live on disk. Forwarded to rsmm via RSMM_MODS_DIR. Empty = rsmm default. */
  modsDir: string;
  sources: string[];
  density: 'cozy' | 'compact';
}

interface State {
  profiles: Profile[];
  activeProfileId: string;
  installed: string[];          // mod IDs in the local library
  settings: AppSettings;
  /** Non-persisted: live mods discovered by rsmm on disk, keyed by id. */
  localMods: Record<string, MockMod>;
  installMod: (id: string) => void;
  uninstallMod: (id: string) => void;
  toggleMod: (id: string) => void;
  reorderMod: (id: string, toIndex: number) => void;
  createProfile: (name: string) => string;
  duplicateProfile: (id: string) => string;
  renameProfile: (id: string, name: string) => void;
  deleteProfile: (id: string) => void;
  setActiveProfile: (id: string) => void;
  exportProfile: (id: string) => string;
  importProfile: (payload: string) => string | null;
  updateSettings: (patch: Partial<AppSettings>) => void;
  /** Sync the live rsmm list into the store: register their metadata
   * and auto-install any new IDs into the active profile. */
  syncLocalMods: (mods: LocalMod[]) => void;
}

function uid(): string {
  return Math.random().toString(36).slice(2, 10);
}

const DEFAULT_PROFILE: Profile = {
  id: 'default',
  name: 'Default',
  loadOrder: ['twin-fang', 'lantern-hud', 'parchment-codex', 'gilt-runes'],
  disabled: new Set(),
  createdAt: new Date().toISOString(),
};

const CHAOS_PROFILE: Profile = {
  id: 'chaos',
  name: 'Chaos Run',
  loadOrder: ['hyper-aggro', 'long-night', 'iron-economy', 'wolfheart-buff', 'wolf-iron-fang'],
  disabled: new Set(),
  createdAt: new Date().toISOString(),
};

export const useApp = create<State>()(
  persist(
    (set, get) => ({
      profiles: [DEFAULT_PROFILE, CHAOS_PROFILE],
      activeProfileId: 'default',
      installed: [
        'twin-fang',
        'lantern-hud',
        'parchment-codex',
        'gilt-runes',
        'hyper-aggro',
        'long-night',
        'iron-economy',
        'wolfheart-buff',
        'wolf-iron-fang',
        'pinned-seed',
      ],
      settings: {
        gameDir: '~/.var/app/com.valvesoftware.Steam/.local/share/Steam/steamapps/common/Ravenswatch',
        backupDir: '~/.local/share/rsmm/backups',
        modsDir: '',
        sources: ['https://rsmm.dev/registry'],
        density: 'cozy',
      },
      localMods: {},

      installMod: (id) =>
        set((s) => {
          if (s.installed.includes(id)) return s;
          const installed = [...s.installed, id];
          const profiles = s.profiles.map((p) =>
            p.id === s.activeProfileId && !p.loadOrder.includes(id)
              ? { ...p, loadOrder: [...p.loadOrder, id] }
              : p,
          );
          return { installed, profiles };
        }),

      uninstallMod: (id) =>
        set((s) => ({
          installed: s.installed.filter((m) => m !== id),
          profiles: s.profiles.map((p) => ({
            ...p,
            loadOrder: p.loadOrder.filter((m) => m !== id),
            disabled: new Set([...p.disabled].filter((m) => m !== id)),
          })),
        })),

      toggleMod: (id) =>
        set((s) => ({
          profiles: s.profiles.map((p) => {
            if (p.id !== s.activeProfileId) return p;
            const next = new Set(p.disabled);
            if (next.has(id)) next.delete(id);
            else next.add(id);
            return { ...p, disabled: next };
          }),
        })),

      reorderMod: (id, toIndex) =>
        set((s) => ({
          profiles: s.profiles.map((p) => {
            if (p.id !== s.activeProfileId) return p;
            const filtered = p.loadOrder.filter((m) => m !== id);
            const idx = Math.max(0, Math.min(toIndex, filtered.length));
            const loadOrder = [...filtered.slice(0, idx), id, ...filtered.slice(idx)];
            return { ...p, loadOrder };
          }),
        })),

      createProfile: (name) => {
        const id = uid();
        set((s) => ({
          profiles: [
            ...s.profiles,
            {
              id,
              name,
              loadOrder: [],
              disabled: new Set(),
              createdAt: new Date().toISOString(),
            },
          ],
          activeProfileId: id,
        }));
        return id;
      },

      duplicateProfile: (sourceId) => {
        const src = get().profiles.find((p) => p.id === sourceId);
        if (!src) return sourceId;
        const id = uid();
        set((s) => ({
          profiles: [
            ...s.profiles,
            {
              id,
              name: `${src.name} (copy)`,
              loadOrder: [...src.loadOrder],
              disabled: new Set(src.disabled),
              createdAt: new Date().toISOString(),
            },
          ],
          activeProfileId: id,
        }));
        return id;
      },

      renameProfile: (id, name) =>
        set((s) => ({
          profiles: s.profiles.map((p) => (p.id === id ? { ...p, name } : p)),
        })),

      deleteProfile: (id) =>
        set((s) => {
          const profiles = s.profiles.filter((p) => p.id !== id);
          const activeProfileId =
            s.activeProfileId === id ? (profiles[0]?.id ?? 'default') : s.activeProfileId;
          return { profiles, activeProfileId };
        }),

      setActiveProfile: (id) => set({ activeProfileId: id }),

      exportProfile: (id) => {
        const p = get().profiles.find((x) => x.id === id);
        if (!p) return '';
        const payload: ProfileSerialized = {
          ...p,
          disabled: [...p.disabled],
        };
        const utf8 = new TextEncoder().encode(JSON.stringify({ kind: 'rsmm-profile', v: 1, profile: payload }));
        const bytes = Array.from(utf8).map((b) => String.fromCodePoint(b)).join('');
        return btoa(bytes);
      },

      importProfile: (payload) => {
        try {
          const binary = atob(payload.trim());
          const bytes = Uint8Array.from(binary, (c) => c.codePointAt(0) ?? 0);
          const decoded = new TextDecoder().decode(bytes);
          const parsed = JSON.parse(decoded);
          if (parsed.kind !== 'rsmm-profile' || !parsed.profile) return null;
          const incoming = parsed.profile as ProfileSerialized;
          const id = uid();
          set((s) => ({
            profiles: [
              ...s.profiles,
              {
                id,
                name: `${incoming.name} (imported)`,
                loadOrder: incoming.loadOrder ?? [],
                disabled: new Set(incoming.disabled ?? []),
                createdAt: new Date().toISOString(),
              },
            ],
            activeProfileId: id,
          }));
          return id;
        } catch {
          return null;
        }
      },

      updateSettings: (patch) =>
        set((s) => ({ settings: { ...s.settings, ...patch } })),

      syncLocalMods: (mods) =>
        set((s) => {
          const localMods: Record<string, MockMod> = {};
          for (const m of mods) {
            localMods[m.id] = toMockMod(m, s.localMods[m.id]);
          }
          const known = new Set([...s.installed, ...MOCK_MODS.map((m) => m.id)]);
          const newIds = mods.map((m) => m.id).filter((id) => !known.has(id));
          if (newIds.length === 0) return { localMods };
          const installed = [...s.installed, ...newIds];
          const profiles = s.profiles.map((p) =>
            p.id === s.activeProfileId
              ? {
                  ...p,
                  loadOrder: [
                    ...p.loadOrder,
                    ...newIds.filter((id) => !p.loadOrder.includes(id)),
                  ],
                }
              : p,
          );
          return { localMods, installed, profiles };
        }),
    }),
    {
      name: 'rsmm-grimoire',
      partialize: (s) => {
        const { localMods: _omit, ...rest } = s;
        return rest;
      },
      storage: createJSONStorage(() => localStorage, {
        replacer: (_k, value) =>
          value instanceof Set ? { __rsmm_set: [...value] } : value,
        reviver: (_k, value) => {
          if (
            value &&
            typeof value === 'object' &&
            !Array.isArray(value) &&
            Object.keys(value).length === 1 &&
            '__rsmm_set' in value
          ) {
            const arr = (value as { __rsmm_set: unknown[] }).__rsmm_set;
            if (Array.isArray(arr) && arr.every((x) => typeof x === 'string')) {
              return new Set(arr as string[]);
            }
            return new Set<string>();
          }
          // Back-compat: read legacy `__set` payloads written by older builds.
          if (
            value &&
            typeof value === 'object' &&
            !Array.isArray(value) &&
            Object.keys(value).length === 1 &&
            '__set' in value
          ) {
            const arr = (value as { __set: unknown[] }).__set;
            if (Array.isArray(arr) && arr.every((x) => typeof x === 'string')) {
              return new Set(arr as string[]);
            }
            return new Set<string>();
          }
          return value;
        },
      }),
    },
  ),
);

/** Lookup runs over the live rsmm registry first, then the bundled mocks. */
export function getMod(id: string): MockMod | undefined {
  const live = useApp.getState().localMods[id];
  if (live) return live;
  return MOCK_MODS.find((m) => m.id === id);
}

/** Subscribes to localMods so the consumer re-renders when the registry shifts. */
export function useMod(id: string): MockMod | undefined {
  const live = useApp((s) => s.localMods[id]);
  if (live) return live;
  return MOCK_MODS.find((m) => m.id === id);
}

function inferCategory(tags: string[]): ModCategory {
  const t = tags.map((x) => x.toLowerCase());
  if (t.some((x) => ['cosmetic', 'skin', 'texture', 'reskin'].includes(x))) return 'cosmetic';
  if (t.some((x) => ['balance', 'buff', 'nerf'].includes(x))) return 'balance';
  if (t.some((x) => ['qol', 'ui', 'hud'].includes(x))) return 'qol';
  if (t.some((x) => ['audio', 'sfx', 'music'].includes(x))) return 'audio';
  if (t.some((x) => ['difficulty', 'hard', 'challenge'].includes(x))) return 'difficulty';
  if (t.some((x) => ['speedrun'].includes(x))) return 'speedrun';
  if (t.some((x) => ['utility', 'tool', 'dev'].includes(x))) return 'utility';
  return 'gameplay';
}

function toMockMod(m: LocalMod, prev?: MockMod): MockMod {
  const summary = m.summary ?? '';
  return {
    id: m.id,
    slug: m.slug,
    name: m.name,
    author: m.author ?? 'unknown',
    version: m.version,
    latestVersion: prev?.latestVersion ?? m.version,
    category: prev?.category ?? inferCategory(m.tags),
    summary,
    description: prev?.description ?? summary,
    changelog: prev?.changelog ?? '',
    rating: prev?.rating ?? 0,
    downloads: prev?.downloads ?? 0,
    sizeKb: prev?.sizeKb ?? 0,
    tags: m.tags,
    dependencies: prev?.dependencies ?? [],
    writes: prev?.writes ?? [],
    gameBuild: prev?.gameBuild ?? '',
    image: prev?.image,
    markdown: prev?.markdown ?? (summary ? `# ${m.name}\n\n${summary}` : `# ${m.name}`),
  };
}

export function activeProfile(s: State): Profile {
  const found = s.profiles.find((p) => p.id === s.activeProfileId) ?? s.profiles[0];
  if (!found) throw new Error('no profiles defined');
  return found;
}

export interface Conflict {
  path: string;
  modIds: string[];
}

/** File-path conflicts among enabled mods in a profile. */
export function detectConflicts(profile: Profile): Conflict[] {
  const writers = new Map<string, string[]>();
  for (const modId of profile.loadOrder) {
    if (profile.disabled.has(modId)) continue;
    const mod = getMod(modId);
    if (!mod) continue;
    for (const path of mod.writes) {
      const list = writers.get(path) ?? [];
      list.push(modId);
      writers.set(path, list);
    }
  }
  const conflicts: Conflict[] = [];
  for (const [path, modIds] of writers) {
    if (modIds.length > 1) conflicts.push({ path, modIds });
  }
  return conflicts;
}

export function outdatedCount(installed: string[]): number {
  return installed.filter((id) => {
    const m = getMod(id);
    return m && m.version !== m.latestVersion;
  }).length;
}
