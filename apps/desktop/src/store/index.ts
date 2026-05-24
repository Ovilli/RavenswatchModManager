import { create } from 'zustand';
import { createJSONStorage, persist } from 'zustand/middleware';
import type { MockMod, ModCategory } from '../data/mock-mods';
import { getPlatform } from '../lib/platform';
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
  installed: string[]; // mod IDs present in the local mod folder
  settings: AppSettings;
  /** Non-persisted: live mods discovered by rsmm on disk, keyed by id. */
  localMods: Record<string, MockMod>;
  installMod: (id: string, targetProfileId?: string) => void;
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
  exportBackup: () => string;
  importBackup: (payload: string) => string | null;
  updateSettings: (patch: Partial<AppSettings>) => void;
  /** Sync the live rsmm list into the store and keep profiles in sync
   * with what is actually present on disk. */
  syncLocalMods: (mods: LocalMod[]) => void;
  /** Patch latestVersion + image/summary onto local mods after polling the API. */
  patchRemoteInfo: (info: Record<string, { latestVersion?: string | null; image?: string | null; summary?: string | null }>) => void;
}

function uid(): string {
  return Math.random().toString(36).slice(2, 10);
}

function defaultGameDir(): string {
  switch (getPlatform()) {
    case 'windows':
      return 'C:\\Program Files (x86)\\Steam\\steamapps\\common\\Ravenswatch';
    case 'macos':
      return '~/Library/Application Support/Steam/steamapps/common/Ravenswatch/Ravenswatch.app';
    default:
      return '~/.steam/steam/steamapps/common/Ravenswatch';
  }
}

const DEFAULT_PROFILE: Profile = {
  id: 'default',
  name: 'Default',
  loadOrder: [],
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

function normalizeDisabled(disabled: Profile['disabled'] | string[] | undefined): Set<string> {
  if (disabled instanceof Set) return new Set(disabled);
  if (Array.isArray(disabled)) return new Set(disabled.filter((x) => typeof x === 'string'));
  return new Set<string>();
}

/** Map legacy API UUIDs / slug aliases to the on-disk mod folder id. */
function canonicalModId(
  id: string,
  localMods: Record<string, MockMod>,
  installedSet: Set<string>,
): string | null {
  if (installedSet.has(id)) return id;
  const bySlug = Object.values(localMods).find((m) => m.slug === id);
  if (bySlug && installedSet.has(bySlug.id)) return bySlug.id;
  return null;
}

function resolveModId(
  id: string,
  localMods: Record<string, MockMod>,
  installed: string[],
): string {
  const installedSet = new Set(installed);
  return (
    canonicalModId(id, localMods, installedSet) ??
    (localMods[id] ? id : Object.values(localMods).find((m) => m.slug === id)?.id ?? id)
  );
}

function normalizeProfiles(profiles: Profile[] | undefined): Profile[] {
  const list = (profiles ?? []).map((p) => ({
    ...p,
    disabled: normalizeDisabled(p.disabled as Profile['disabled'] | string[] | undefined),
  }));

  const byId = new Map(list.map((p) => [p.id, p]));
  const existingDefault = byId.get('default');
  const defaultProfile: Profile = existingDefault
    ? {
        ...existingDefault,
        name: existingDefault.name || 'Default',
        loadOrder: [],
        disabled: new Set<string>(),
      }
    : {
        ...DEFAULT_PROFILE,
        disabled: new Set<string>(),
      };

  const rest = list.filter((p) => p.id !== 'default');
  return [defaultProfile, ...rest];
}

export const useApp = create<State>()(
  persist(
    (set, get) => ({
      profiles: [DEFAULT_PROFILE, CHAOS_PROFILE],
      activeProfileId: 'default',
      installed: [],
      settings: {
        gameDir: defaultGameDir(),
        backupDir:
          getPlatform() === 'windows'
            ? '%LOCALAPPDATA%\\rsmm\\backups'
            : '~/.local/share/rsmm/backups',
        modsDir: '',
        sources: ['https://rsmm.dev/registry'],
        density: 'cozy',
      },
      localMods: {},

      installMod: (id, targetProfileId) =>
        set((s) => {
          // "Install" = make the mod available on disk + add it to a
          // target profile. Caller may pass an explicit profile id (the
          // Browse-page picker uses this); otherwise the active profile
          // is used. Default profile is the vanilla load by design and
          // never accepts mods — installs targeting default are routed
          // to a freshly-created "My Mods" profile so the user actually
          // sees the mod in their Library.
          //
          // Always store folder slugs in loadOrder — never API UUIDs
          // (mod detail used to pass apiMod.id, which syncLocalMods pruned).
          const modId = resolveModId(id, s.localMods, s.installed);
          const installed = s.installed.includes(modId)
            ? s.installed
            : [...s.installed, modId];
          const requested = targetProfileId ?? s.activeProfileId;
          if (requested === 'default') {
            const newId = uid();
            const newProfile: Profile = {
              id: newId,
              name: 'My Mods',
              loadOrder: [modId],
              disabled: new Set(),
              createdAt: new Date().toISOString(),
            };
            return {
              installed,
              profiles: [...s.profiles, newProfile],
              activeProfileId: newId,
            };
          }
          const profiles = s.profiles.map((p) => {
            if (p.id !== requested) return p;
            if (p.loadOrder.includes(modId)) return p;
            return { ...p, loadOrder: [...p.loadOrder, modId] };
          });
          return { installed, profiles, activeProfileId: requested };
        }),

      uninstallMod: (id) =>
        set((s) => {
          // Per-profile removal. Uninstalling Mod X from Profile A must
          // *not* nuke it from Profile B's library; that surprised users
          // who expected each profile to be its own bucket. The mod
          // stays on disk (in `installed`) so the user can re-add it to
          // any profile without re-downloading.
          //
          // The default profile is the "vanilla" load — by design it
          // carries no mods, so the active profile guard already covers
          // the no-op case.
          const modId = resolveModId(id, s.localMods, s.installed);
          const profiles = s.profiles.map((p) => {
            if (p.id !== s.activeProfileId) return p;
            return {
              ...p,
              loadOrder: p.loadOrder.filter(
                (m) => resolveModId(m, s.localMods, s.installed) !== modId,
              ),
              disabled: new Set(
                [...p.disabled].filter(
                  (m) => resolveModId(m, s.localMods, s.installed) !== modId,
                ),
              ),
            };
          });
          return { profiles };
        }),

      toggleMod: (id) =>
        set((s) => {
          const modId = resolveModId(id, s.localMods, s.installed);
          return {
            profiles: s.profiles.map((p) => {
              if (p.id !== s.activeProfileId) return p;
              // A mod is *enabled in this profile* iff it's in `loadOrder`
              // and NOT in `disabled`. Toggle flips that bit while making
              // sure the profile actually contains the mod — without this
              // the default profile (empty loadOrder, empty disabled) had
              // mods showing as enabled-but-not-in-load-order, so the
              // header counter (gates on loadOrder) and the library rows
              // (gated only on `disabled`) disagreed.
              const inLoadOrder = p.loadOrder.includes(modId);
              const isEnabled = inLoadOrder && !p.disabled.has(modId);
              const disabled = new Set(p.disabled);
              if (isEnabled) {
                disabled.add(modId);
                return { ...p, disabled };
              }
              disabled.delete(modId);
              const loadOrder = inLoadOrder ? p.loadOrder : [...p.loadOrder, modId];
              return { ...p, loadOrder, disabled };
            }),
          };
        }),

      reorderMod: (id, toIndex) =>
        set((s) => {
          const modId = resolveModId(id, s.localMods, s.installed);
          return {
            profiles: s.profiles.map((p) => {
              if (p.id !== s.activeProfileId) return p;
              const filtered = p.loadOrder.filter(
                (m) => resolveModId(m, s.localMods, s.installed) !== modId,
              );
              const idx = Math.max(0, Math.min(toIndex, filtered.length));
              const loadOrder = [...filtered.slice(0, idx), modId, ...filtered.slice(idx)];
              return { ...p, loadOrder };
            }),
          };
        }),

      createProfile: (name) => {
        const id = uid();
        set((s) => ({
          profiles: [
            ...s.profiles,
            {
              id,
              name,
              // New profile starts EMPTY by design — each profile is
              // its own bucket, and the user explicitly opts mods in
              // via Browse → Install (or Library → Add). Auto-seeding
              // from the global `installed` list surprised users who
              // expected a "fresh slate" profile.
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
        const utf8 = new TextEncoder().encode(
          JSON.stringify({ kind: 'rsmm-profile', v: 1, profile: payload }),
        );
        const bytes = Array.from(utf8)
          .map((b) => String.fromCodePoint(b))
          .join('');
        return btoa(bytes);
      },

      exportBackup: () => {
        const state = get();
        const payload = {
          kind: 'rsmm-backup',
          v: 1,
          settings: state.settings,
          activeProfileId: state.activeProfileId,
          profiles: state.profiles.map((p) => ({
            ...p,
            disabled: [...p.disabled],
          })),
        };
        const utf8 = new TextEncoder().encode(JSON.stringify(payload));
        const bytes = Array.from(utf8)
          .map((b) => String.fromCodePoint(b))
          .join('');
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

      importBackup: (payload) => {
        try {
          const binary = atob(payload.trim());
          const bytes = Uint8Array.from(binary, (c) => c.codePointAt(0) ?? 0);
          const decoded = new TextDecoder().decode(bytes);
          const parsed = JSON.parse(decoded);
          if (parsed.kind !== 'rsmm-backup' || !Array.isArray(parsed.profiles)) return null;
          const profiles = normalizeProfiles(
            parsed.profiles.map((p: ProfileSerialized) => ({
              ...p,
              disabled: new Set(p.disabled ?? []),
            })),
          );
          set({
            profiles,
            activeProfileId:
              profiles.some((p) => p.id === parsed.activeProfileId) ? parsed.activeProfileId : 'default',
            settings: {
              ...get().settings,
              ...(parsed.settings ?? {}),
            },
          });
          return 'ok';
        } catch {
          return null;
        }
      },

      updateSettings: (patch) => set((s) => ({ settings: { ...s.settings, ...patch } })),

      syncLocalMods: (mods) =>
        set((s) => {
          const localMods: Record<string, MockMod> = {};
          for (const m of mods) {
            localMods[m.id] = toMockMod(m, s.localMods[m.id]);
          }
          const installed = mods.map((m) => m.id);
          const installedSet = new Set(installed);
          const profiles = s.profiles.map((p) => {
            if (p.id === 'default') {
              return { ...p, loadOrder: [], disabled: new Set<string>() };
            }
            const loadOrder: string[] = [];
            for (const entry of p.loadOrder) {
              const canon = canonicalModId(entry, localMods, installedSet);
              if (canon && !loadOrder.includes(canon)) loadOrder.push(canon);
            }
            const disabled = new Set(
              [...p.disabled]
                .map((entry) => canonicalModId(entry, localMods, installedSet))
                .filter((entry): entry is string => entry != null),
            );
            return { ...p, loadOrder, disabled };
          });
          return { localMods, installed, profiles };
        }),

      patchRemoteInfo: (info) =>
        set((s) => {
          const next: Record<string, MockMod> = { ...s.localMods };
          for (const [slug, payload] of Object.entries(info)) {
            const found = Object.values(next).find((m) => m.slug === slug);
            if (!found) continue;
            next[found.id] = {
              ...found,
              latestVersion: payload.latestVersion ?? found.latestVersion,
              image: payload.image ?? found.image,
              summary: payload.summary ?? found.summary,
            };
          }
          return { localMods: next };
        }),
    }),
    {
      name: 'rsmm-grimoire',
      merge: (persisted, current) => {
        const merged = {
          ...(current as State),
          ...(persisted as Partial<State>),
        };
        const profiles = normalizeProfiles(merged.profiles);
        const activeProfileId = profiles.some((p) => p.id === merged.activeProfileId)
          ? merged.activeProfileId
          : 'default';
        return {
          ...merged,
          profiles,
          activeProfileId,
        };
      },
      partialize: (s) => {
        const { localMods: _omit, ...rest } = s;
        return rest;
      },
      storage: createJSONStorage(() => localStorage, {
        replacer: (_k, value) => (value instanceof Set ? { __rsmm_set: [...value] } : value),
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

/**
 * Lookup runs over the live rsmm registry only.
 *
 * The library/conflicts/command-palette views iterate over the
 * profile's load order, which is itself a subset of `installed`, so a
 * `getMod()` miss here means the mod is in a profile but not present
 * on disk — that's the `syncLocalMods` prune path's job to fix.
 */
export function getMod(id: string): MockMod | undefined {
  return useApp.getState().localMods[id];
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
    dependencies: Object.keys(m.dependencies).length > 0 ? Object.keys(m.dependencies) : prev?.dependencies ?? [],
    writes: m.writes.length > 0 ? m.writes : prev?.writes ?? [],
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

/**
 * Single source of truth for "is this mod enabled in this profile?".
 *
 * Membership-in-profile lives in `loadOrder`; `disabled` is the
 * per-profile *exception* set. Every UI surface that needs an enabled
 * flag (library rows, mod detail, conflict picker, counters) must use
 * this helper so the answer can't diverge across components.
 */
export function isEnabledIn(profile: Profile, modId: string): boolean {
  return profile.loadOrder.includes(modId) && !profile.disabled.has(modId);
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

export function outdatedMods(installed: string[]): MockMod[] {
  const out: MockMod[] = [];
  for (const id of installed) {
    const m = getMod(id);
    if (m?.latestVersion && m.version !== m.latestVersion) out.push(m);
  }
  return out;
}
