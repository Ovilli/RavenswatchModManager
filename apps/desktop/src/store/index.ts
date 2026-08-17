import { create } from 'zustand';
import { createJSONStorage, persist } from 'zustand/middleware';
import {
  DEFAULT_FONT,
  DEFAULT_FONT_SCALE,
  type Density,
  type FontChoice,
  normalizeDensity,
  normalizeFont,
  normalizeFontScale,
} from '../lib/appearance';
import type { Mod, ModCategory } from '../lib/mod-types';
import { getPlatform } from '../lib/platform';
import type { LocalMod } from '../lib/rsmm';
import { compareVersions } from '../lib/version';

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

export type ImportResult = { ok: true } | { ok: false; reason: string };

type ShareDecode = { ok: true; data: Record<string, unknown> } | { ok: false; reason: string };

/**
 * Decode an exported share/backup code (base64 of JSON) and verify its
 * `kind`. Returns a *specific* reason on failure so the UI can tell the
 * user what's wrong (bad base64 vs corrupt JSON vs wrong code type)
 * instead of swallowing the error behind a generic "could not read".
 */
function decodeShareCode(payload: string, expectedKind: string): ShareDecode {
  let json: string;
  try {
    const binary = atob(payload.trim());
    const bytes = Uint8Array.from(binary, (c) => c.codePointAt(0) ?? 0);
    json = new TextDecoder().decode(bytes);
  } catch {
    return { ok: false, reason: 'That is not a valid code (bad base64).' };
  }
  let parsed: unknown;
  try {
    parsed = JSON.parse(json);
  } catch {
    return { ok: false, reason: 'The code is corrupt (invalid JSON).' };
  }
  if (
    !parsed ||
    typeof parsed !== 'object' ||
    (parsed as { kind?: unknown }).kind !== expectedKind
  ) {
    return { ok: false, reason: `That is not an ${expectedKind} code.` };
  }
  return { ok: true, data: parsed as Record<string, unknown> };
}

export interface AppSettings {
  gameDir: string;
  backupDir: string;
  /** Folder where mods live on disk. Forwarded to rsmm via RSMM_MODS_DIR. Empty = rsmm default. */
  modsDir: string;
  sources: string[];
  /** Spacing preset. Applied by `applyAppearance` as `data-density` on <html>. */
  density: Density;
  /** UI typeface preset. Applied by `applyAppearance` as CSS vars on <html>. */
  fontFamily: FontChoice;
  /** Root font size as a percentage of the browser default (16px). Every
   * rem-based utility scales with it, so this resizes the whole UI. */
  fontScale: number;
  /** When false, NSFW mod images are blurred. */
  showNsfw: boolean;
  /** Send frontend crash reports to the RSMM API. Local launcher-log entries
   * are written either way — this only controls what leaves the machine. */
  crashReports: boolean;
}

interface State {
  profiles: Profile[];
  activeProfileId: string;
  /**
   * Mod IDs present in the local mod folder. Derived from the last successful
   * `rsmm json list`, and deliberately NOT persisted: it is a fact about the
   * disk, not user state. Persisting it meant a rehydrated session claimed
   * mods were installed that had since been deleted — Browse then disabled
   * its own install button for a mod that wasn't there.
   */
  installed: string[];
  settings: AppSettings;
  /** Non-persisted: live mods discovered by rsmm on disk, keyed by id. */
  localMods: Record<string, Mod>;
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
  importBackup: (payload: string) => ImportResult;
  updateSettings: (patch: Partial<AppSettings>) => void;
  /** Sync the live rsmm list into the store and keep profiles in sync
   * with what is actually present on disk. */
  syncLocalMods: (mods: LocalMod[]) => void;
  /**
   * Drop every entry in a profile that has no mod on disk, and return how
   * many were removed. Explicit and user-triggered: the sync path keeps
   * unknown ids on purpose (a half-finished install must not be erased by
   * the next poll), so this is the escape hatch when they're truly stale.
   */
  pruneMissingMods: (profileId: string) => number;
  /** Add on-disk mods to a profile (the Library's "adopt" action). */
  adoptMods: (ids: string[], profileId?: string) => void;
  /** Patch latestVersion + image/summary onto local mods after polling the API. */
  patchRemoteInfo: (
    info: Record<
      string,
      {
        latestVersion?: string | null;
        image?: string | null;
        summary?: string | null;
        nsfw?: boolean | null;
      }
    >,
  ) => void;
}

function uid(): string {
  return Math.random().toString(36).slice(2, 10);
}

function defaultGameDir(): string {
  switch (getPlatform()) {
    case 'windows':
      return 'C:\\Program Files (x86)\\Steam\\steamapps\\common\\Ravenswatch';
    default:
      return '~/.steam/steam/steamapps/common/Ravenswatch';
  }
}

function defaultModsDir(): string {
  switch (getPlatform()) {
    case 'windows':
      return '%APPDATA%\\rsmm\\mods';
    default:
      return '~/.local/share/rsmm/mods';
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
  localMods: Record<string, Mod>,
  installedSet: Set<string>,
): string | null {
  if (installedSet.has(id)) return id;
  const bySlug = Object.values(localMods).find((m) => m.slug === id);
  if (bySlug && installedSet.has(bySlug.id)) return bySlug.id;
  return null;
}

function resolveModId(id: string, localMods: Record<string, Mod>, installed: string[]): string {
  const installedSet = new Set(installed);
  return (
    canonicalModId(id, localMods, installedSet) ??
    (localMods[id] ? id : (Object.values(localMods).find((m) => m.slug === id)?.id ?? id))
  );
}

function modWasOnDisk(id: string, previous: Record<string, Mod>): boolean {
  if (previous[id]) return true;
  return Object.values(previous).some((m) => m.id === id || m.slug === id);
}

/** Keep profile mod ids across stale rsmm list polls; drop only confirmed removals. */
function reconcileProfileModIds(
  entries: Iterable<string>,
  localMods: Record<string, Mod>,
  previousLocalMods: Record<string, Mod>,
  installedSet: Set<string>,
): string[] {
  const out: string[] = [];
  const hasAnyMods = Object.keys(localMods).length > 0;
  for (const entry of entries) {
    const canon = canonicalModId(entry, localMods, installedSet);
    if (canon) {
      if (!out.includes(canon)) out.push(canon);
      continue;
    }
    // Only prune mods when the CLI successfully enumerated at least
    // one mod — an empty list likely means a transient CLI error
    // (CLI not ready, temporary FS issue), not that every mod was
    // intentionally removed. Pruning on partial data permanently
    // loses mods from the profile.
    if (hasAnyMods && modWasOnDisk(entry, previousLocalMods)) {
      continue;
    }
    if (!out.includes(entry)) out.push(entry);
  }
  return out;
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

/**
 * Fold a persisted settings blob onto the current defaults.
 *
 * Field-by-field, because zustand's `merge` spreads the persisted state over
 * the fresh one: a store written before a setting existed would otherwise
 * carry that key as `undefined` forever. The appearance keys are additionally
 * sanitized — they are read straight into CSS, so a hand-edited or truncated
 * localStorage value must not reach the stylesheet.
 */
export function hydrateSettings(
  defaults: AppSettings,
  persisted: Partial<AppSettings> | undefined,
): AppSettings {
  const merged: AppSettings = { ...defaults, ...(persisted ?? {}) };
  return {
    ...merged,
    fontFamily: normalizeFont(merged.fontFamily),
    fontScale: normalizeFontScale(merged.fontScale),
    density: normalizeDensity(merged.density),
    // Anything that isn't an explicit `false` keeps reporting on — but a
    // stored `false` must survive, so this can't be a truthiness coercion
    // of a possibly-undefined value.
    crashReports: merged.crashReports !== false,
  };
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
        modsDir: defaultModsDir(),
        showNsfw: false,
        sources: ['https://rsmm.me/registry'],
        density: 'cozy',
        crashReports: true,
        fontFamily: DEFAULT_FONT,
        fontScale: DEFAULT_FONT_SCALE,
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
          const installed = s.installed.includes(modId) ? s.installed : [...s.installed, modId];
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
            if (p.loadOrder.includes(modId)) {
              if (p.disabled.has(modId)) {
                const disabled = new Set(p.disabled);
                disabled.delete(modId);
                return { ...p, disabled };
              }
              return p;
            }
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
                [...p.disabled].filter((m) => resolveModId(m, s.localMods, s.installed) !== modId),
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
        const decoded = decodeShareCode(payload, 'rsmm-profile');
        if (!decoded.ok) {
          console.error('[importProfile]', decoded.reason);
          return null;
        }
        const parsed = decoded.data;
        if (!parsed.profile) {
          console.error('[importProfile] code has no profile payload');
          return null;
        }
        try {
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
        const decoded = decodeShareCode(payload, 'rsmm-backup');
        if (!decoded.ok) return decoded;
        const parsed = decoded.data as {
          profiles?: unknown;
          activeProfileId?: string;
          settings?: Partial<AppSettings>;
        };
        if (!Array.isArray(parsed.profiles)) {
          return { ok: false, reason: 'Backup contains no profiles.' };
        }
        try {
          const profiles = normalizeProfiles(
            parsed.profiles.map((p: ProfileSerialized) => ({
              ...p,
              disabled: new Set(p.disabled ?? []),
            })),
          );
          set({
            profiles,
            activeProfileId: profiles.some((p) => p.id === parsed.activeProfileId)
              ? (parsed.activeProfileId as string)
              : 'default',
            // Same sanitizing path as rehydrate: a backup file is user-supplied
            // data, and its appearance keys are read straight into CSS.
            settings: hydrateSettings(get().settings, parsed.settings),
          });
          return { ok: true };
        } catch (e) {
          return {
            ok: false,
            reason: `Backup is malformed: ${e instanceof Error ? e.message : String(e)}`,
          };
        }
      },

      updateSettings: (patch) => set((s) => ({ settings: { ...s.settings, ...patch } })),

      syncLocalMods: (mods) =>
        set((s) => {
          const localMods: Record<string, Mod> = {};
          for (const m of mods) {
            localMods[m.id] = toMod(m, s.localMods[m.id]);
          }
          const installedSet = new Set(mods.map((m) => m.id));
          const profiles = s.profiles.map((p) => {
            if (p.id === 'default') {
              return { ...p, loadOrder: [], disabled: new Set<string>() };
            }
            const loadOrder = reconcileProfileModIds(
              p.loadOrder,
              localMods,
              s.localMods,
              installedSet,
            );
            // Don't augment installedSet with loadOrder entries — it should
            // reflect only what's actually on disk, not what profiles expect.
            // Profile mods are kept by reconcileProfileModIds regardless.
            const disabled = new Set(
              reconcileProfileModIds(p.disabled, localMods, s.localMods, installedSet),
            );
            return { ...p, loadOrder, disabled };
          });
          const installed = [...installedSet];
          return { localMods, installed, profiles };
        }),

      pruneMissingMods: (profileId) => {
        const s = get();
        const profile = s.profiles.find((p) => p.id === profileId);
        if (!profile) return 0;
        const onDisk = new Set(Object.keys(s.localMods));
        const keep = profile.loadOrder.filter((id) => onDisk.has(id));
        const removed = profile.loadOrder.length - keep.length;
        if (removed === 0) return 0;
        set({
          profiles: s.profiles.map((p) =>
            p.id === profileId
              ? {
                  ...p,
                  loadOrder: keep,
                  disabled: new Set([...p.disabled].filter((id) => onDisk.has(id))),
                }
              : p,
          ),
        });
        return removed;
      },

      adoptMods: (ids, profileId) =>
        set((s) => {
          const target = profileId ?? s.activeProfileId;
          // The default profile is the vanilla load and never carries mods,
          // so adopting into it would silently do nothing.
          if (target === 'default') return s;
          return {
            profiles: s.profiles.map((p) => {
              if (p.id !== target) return p;
              const add = ids.filter((id) => !p.loadOrder.includes(id));
              if (add.length === 0) return p;
              return { ...p, loadOrder: [...p.loadOrder, ...add] };
            }),
          };
        }),

      patchRemoteInfo: (info) =>
        set((s) => {
          const next: Record<string, Mod> = { ...s.localMods };
          for (const [slug, payload] of Object.entries(info)) {
            const found = Object.values(next).find((m) => m.slug === slug);
            if (!found) continue;
            next[found.id] = {
              ...found,
              latestVersion: payload.latestVersion ?? found.latestVersion,
              image: payload.image ?? found.image,
              summary: payload.summary ?? found.summary,
              nsfw: payload.nsfw ?? found.nsfw,
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
        merged.settings = hydrateSettings((current as State).settings, merged.settings);
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
      // `localMods` and `installed` are both disk facts, re-derived on every
      // successful `rsmm json list`. Persisting either one lets a stale
      // snapshot outlive the thing it describes.
      partialize: (s) => {
        const { localMods: _omitMods, installed: _omitInstalled, ...rest } = s;
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
export function getMod(id: string): Mod | undefined {
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

function toMod(m: LocalMod, prev?: Mod): Mod {
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
    dependencies:
      Object.keys(m.dependencies).length > 0
        ? Object.keys(m.dependencies)
        : (prev?.dependencies ?? []),
    writes: m.writes.length > 0 ? m.writes : (prev?.writes ?? []),
    gameBuild: prev?.gameBuild ?? '',
    image: prev?.image,
    markdown: prev?.markdown ?? (summary ? `# ${m.name}\n\n${summary}` : `# ${m.name}`),
    nsfw: prev?.nsfw ?? false,
    // `?? prev` so an older sidecar (which omits the field) doesn't erase what
    // a previous, newer answer established.
    hasConfig: m.hasConfig ?? prev?.hasConfig ?? false,
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
 * Split a profile's load order into entries backed by a mod on disk and
 * entries that are not.
 *
 * A profile keeps ids the CLI can't see — an install that failed halfway, a
 * folder deleted outside the app, a legacy API UUID. That's deliberate (the
 * user may reinstall), but every count and list must be honest about it:
 * showing "12 total" for a profile whose mods are all gone, or listing a raw
 * UUID as though it were a disabled mod, is what made profiles look full when
 * they were empty.
 */
export function splitProfileMods(profile: Profile): { present: string[]; missing: string[] } {
  const present: string[] = [];
  const missing: string[] = [];
  for (const id of profile.loadOrder) {
    (getMod(id) ? present : missing).push(id);
  }
  return { present, missing };
}

/** Mods on disk that this profile hasn't opted into. */
export function unadoptedMods(profile: Profile, installed: string[]): string[] {
  return installed.filter((id) => !profile.loadOrder.includes(id) && Boolean(getMod(id)));
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

// Outdated = the registry's latest orders strictly NEWER than the installed
// version. Plain inequality would also flag a locally-newer build (e.g. a mod
// author testing an unpublished version) and offer it a downgrade as an
// "update".
function isOutdated(m: Mod | undefined): m is Mod {
  return !!m?.latestVersion && compareVersions(m.latestVersion, m.version) > 0;
}

export function outdatedCount(installed: string[]): number {
  return installed.filter((id) => isOutdated(getMod(id))).length;
}

export function outdatedMods(installed: string[]): Mod[] {
  const out: Mod[] = [];
  for (const id of installed) {
    const m = getMod(id);
    if (isOutdated(m)) out.push(m);
  }
  return out;
}
