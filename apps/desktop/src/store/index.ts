import { create } from 'zustand';
import { persist, createJSONStorage } from 'zustand/middleware';
import { MOCK_MODS, type MockMod } from '../data/mock-mods';

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
  sources: string[];
  density: 'cozy' | 'compact';
}

interface State {
  profiles: Profile[];
  activeProfileId: string;
  installed: string[];          // mod IDs in the local library
  settings: AppSettings;
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
        sources: ['https://rsmm.dev/registry'],
        density: 'cozy',
      },

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
            const order = p.loadOrder.filter((m) => m !== id);
            const idx = Math.max(0, Math.min(toIndex, order.length));
            order.splice(idx, 0, id);
            return { ...p, loadOrder: order };
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
        return btoa(JSON.stringify({ kind: 'rsmm-profile', v: 1, profile: payload }));
      },

      importProfile: (payload) => {
        try {
          const parsed = JSON.parse(atob(payload.trim()));
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
    }),
    {
      name: 'rsmm-grimoire',
      storage: createJSONStorage(() => localStorage, {
        replacer: (_k, value) =>
          value instanceof Set ? { __set: [...value] } : value,
        reviver: (_k, value) => {
          if (value && typeof value === 'object' && '__set' in value) {
            return new Set((value as { __set: unknown[] }).__set as string[]);
          }
          return value;
        },
      }),
    },
  ),
);

/** Selectors that read directly from the mock index. */
export function getMod(id: string): MockMod | undefined {
  return MOCK_MODS.find((m) => m.id === id);
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
