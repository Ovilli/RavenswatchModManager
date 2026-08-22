import { useQuery } from '@tanstack/react-query';
import { useNavigate } from '@tanstack/react-router';
import { Search } from 'lucide-react';
import { useEffect, useId, useMemo, useRef, useState } from 'react';
import { api, logApiError } from '../lib/api';
import { type PaletteAction, type PaletteRow, buildRows } from '../lib/palette';
import { toggleOverlay } from '../lib/overlay-windows';
import { listOverlays, restoreAll } from '../lib/rsmm';
import { useApp } from '../store';
import { useLaunch } from './launch';
import { useToast } from './toast';

interface Hit {
  id: string;
  slug: string;
  name: string;
  author: string;
  origin: 'library' | 'remote';
}

export function CommandPalette() {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState('');
  const [cursor, setCursor] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const triggerRef = useRef<HTMLElement | null>(null);
  const installed = useApp((s) => s.installed);
  const localMods = useApp((s) => s.localMods);
  const navigate = useNavigate();
  const listboxId = useId();
  const { launch, busy: launchBusy } = useLaunch();
  const toast = useToast();

  // Remote index search runs only while the palette is open + the user
  // has typed at least 2 chars. React Query caches per `q` so repeated
  // typing doesn't hammer the API.
  const trimmedQ = q.trim();
  const { data: remoteData, error: remoteError } = useQuery({
    queryKey: ['mods', 'palette', trimmedQ],
    queryFn: () => api.mods.list({ q: trimmedQ, limit: 10 }),
    enabled: open && trimmedQ.length >= 2,
    staleTime: 30_000,
  });

  // Don't let "the index is unreachable" masquerade as "no results".
  useEffect(() => {
    if (remoteError) logApiError('command-palette', remoteError);
  }, [remoteError]);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      const meta = e.metaKey || e.ctrlKey;
      if (meta && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        setOpen((o) => !o);
      }
    }
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  useEffect(() => {
    if (open) {
      triggerRef.current = document.activeElement as HTMLElement | null;
      setQ('');
      setCursor(0);
      // Defer to next frame so the input ref is wired up before focus.
      const handle = window.requestAnimationFrame(() => {
        inputRef.current?.focus();
      });
      const trigger = triggerRef.current;
      return () => {
        window.cancelAnimationFrame(handle);
        trigger?.focus?.();
      };
    }
    return;
  }, [open]);

  const hits = useMemo<Hit[]>(() => {
    const needle = trimmedQ.toLowerCase();
    // Empty input: show the first few locally-installed mods as a
    // jumping-off point for the user.
    if (!needle) {
      const out: Hit[] = [];
      for (const id of installed.slice(0, 5)) {
        const m = localMods[id];
        if (m)
          out.push({ id: m.id, slug: m.slug, name: m.name, author: m.author, origin: 'library' });
      }
      return out;
    }
    // Local matches first (no network round-trip, exact for what the
    // user already has on disk).
    const local: Hit[] = installed
      .map((id) => localMods[id])
      .filter(
        (m): m is NonNullable<typeof m> =>
          !!m &&
          (m.name.toLowerCase().includes(needle) ||
            m.slug.toLowerCase().includes(needle) ||
            m.tags.some((t) => t.toLowerCase().includes(needle))),
      )
      .slice(0, 5)
      .map<Hit>((m) => ({
        id: m.id,
        slug: m.slug,
        name: m.name,
        author: m.author,
        origin: 'library',
      }));
    // Remote: dedupe against ids already shown locally; cap total at 10.
    const seen = new Set(local.map((h) => h.id));
    const remote: Hit[] = (remoteData?.items ?? [])
      .filter((m) => !seen.has(m.id))
      .slice(0, Math.max(0, 10 - local.length))
      .map<Hit>((m) => ({
        id: m.id,
        slug: m.slug,
        name: m.name,
        author: m.author ?? 'unknown',
        origin: installed.includes(m.id) ? 'library' : 'remote',
      }));
    return [...local, ...remote];
  }, [trimmedQ, installed, localMods, remoteData]);

  const { data: overlayList } = useQuery({
    queryKey: ['overlays'],
    queryFn: () => listOverlays(),
    // Only needed while the palette is open, and a stale entry is harmless.
    staleTime: 30_000,
    enabled: open,
  });

  const overlayActions = useMemo<PaletteAction[]>(
    () =>
      (overlayList?.overlays ?? [])
        .filter((o) => !o.error)
        .map((o) => ({
          id: `overlay:${o.modId}`,
          label: `Toggle ${o.title ?? o.modId} overlay`,
          keywords: `overlay hud window ${o.modId} ${o.title ?? ''}`,
          hint: 'action',
          run: () => {
            void (async () => {
              try {
                const opened = await toggleOverlay(o.modId);
                toast.push(
                  `${o.title ?? o.modId} overlay ${opened ? 'opened' : 'closed'}.`,
                  'success',
                );
              } catch (e) {
                toast.push(
                  `Overlay failed: ${e instanceof Error ? e.message : String(e)}`,
                  'error',
                );
              }
            })();
          },
        })),
    [overlayList, toast],
  );

  const actions = useMemo<PaletteAction[]>(() => {
    const go = (
      to: '/' | '/browse' | '/profiles' | '/conflicts' | '/commands' | '/settings',
      label: string,
      keywords: string,
      // Settings groups its panels into tabs and `?tab=` opens one directly, so
      // "About" can stay its own palette entry now that it is no longer a page.
      search?: { tab: string },
    ): PaletteAction => ({
      // `to` alone is no longer unique — two entries land on /settings.
      id: `go:${to}${search?.tab ? `?tab=${search.tab}` : ''}`,
      label,
      keywords,
      hint: 'go',
      run: () => navigate(search ? { to, search } : { to }),
    });
    return [
      {
        id: 'launch:modded',
        label: 'Launch Modded',
        keywords: 'play start game run mods',
        hint: launchBusy ? 'busy' : 'action',
        disabled: launchBusy,
        run: () => void launch('modded'),
      },
      {
        id: 'launch:vanilla',
        label: 'Launch Vanilla',
        keywords: 'play start game unmodded clean',
        hint: launchBusy ? 'busy' : 'action',
        disabled: launchBusy,
        run: () => void launch('vanilla'),
      },
      {
        id: 'restore',
        label: 'Restore original files',
        keywords: 'undo unapply revert vanilla clean uninstall',
        hint: launchBusy ? 'busy' : 'action',
        disabled: launchBusy,
        run: () => {
          void (async () => {
            try {
              const result = await restoreAll();
              if (!result || !result.ok)
                throw new Error(result?.stderr?.trim() || 'restore failed');
              toast.push('Original files restored.', 'success');
            } catch (e) {
              toast.push(`Restore failed: ${e instanceof Error ? e.message : String(e)}`, 'error');
            }
          })();
        },
      },
      // One entry per mod-declared overlay — the client hardcodes none of
      // them, so a newly installed mod's HUD shows up here on its own.
      ...overlayActions,
      go('/', 'Library', 'mods installed home'),
      go('/browse', 'Browse mods', 'search index download store'),
      go('/profiles', 'Profiles', 'loadout preset switch'),
      go('/conflicts', 'Conflicts', 'clash overlap same file'),
      go('/commands', 'Commands', 'apply build doctor terminal'),
      go('/settings', 'Settings', 'paths font size density options preferences'),
      go('/settings', 'About', 'version credits release notes', { tab: 'about' }),
    ];
  }, [navigate, launch, launchBusy, toast, overlayActions]);

  const rows = useMemo<PaletteRow[]>(
    () => buildRows(actions, hits, trimmedQ),
    [actions, hits, trimmedQ],
  );

  if (!open) return null;

  function commit(idx: number) {
    const row = rows[idx];
    if (!row) return;
    if (row.kind === 'action') {
      if (row.action.disabled) return;
      setOpen(false);
      row.action.run();
      return;
    }
    setOpen(false);
    navigate({ to: '/mod/$slug', params: { slug: row.hit.slug } });
  }

  return (
    <dialog
      open
      aria-label="Search mods and commands"
      className="fixed inset-0 z-50 flex items-start justify-center pt-[12vh] animate-fade-in"
      onClick={() => setOpen(false)}
      onKeyDown={(e) => {
        if (e.key === 'Escape') {
          e.preventDefault();
          setOpen(false);
        }
      }}
    >
      <div className="absolute inset-0 bg-pitch/80" />
      <div
        className="grimoire-card relative w-[min(620px,90vw)] p-2"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center gap-3 border-b border-border px-3 py-2">
          <Search className="h-4 w-4 text-ash" aria-hidden />
          <input
            ref={inputRef}
            value={q}
            onChange={(e) => {
              setQ(e.target.value);
              setCursor(0);
            }}
            onKeyDown={(e) => {
              if (e.key === 'ArrowDown') {
                e.preventDefault();
                setCursor((c) => Math.min(c + 1, rows.length - 1));
              } else if (e.key === 'ArrowUp') {
                e.preventDefault();
                setCursor((c) => Math.max(c - 1, 0));
              } else if (e.key === 'Home') {
                e.preventDefault();
                setCursor(0);
              } else if (e.key === 'End') {
                e.preventDefault();
                setCursor(Math.max(rows.length - 1, 0));
              } else if (e.key === 'Enter') {
                e.preventDefault();
                commit(cursor);
              }
            }}
            placeholder="Search mods, or type a command — launch, restore, settings…"
            className="w-full bg-transparent text-parchment placeholder:text-ash focus:outline-none"
            role="combobox"
            aria-expanded={true}
            aria-controls={listboxId}
            aria-activedescendant={rows[cursor] ? `${listboxId}-opt-${cursor}` : undefined}
            aria-autocomplete="list"
          />
          <span className="font-mono text-ash">ESC</span>
        </div>
        <div
          id={listboxId}
          // biome-ignore lint/a11y/useSemanticElements: custom combobox results list — no native element implements the listbox interaction
          role="listbox"
          aria-label="Search results"
          className="max-h-[50vh] overflow-y-auto py-2"
        >
          {rows.length === 0 ? (
            <div className="font-serif-italic px-4 py-6 text-center text-ash">
              {remoteError && trimmedQ.length >= 2
                ? 'Nothing matches here — and the remote index is unreachable, so online results are unavailable.'
                : 'Nothing matches. Try a different word.'}
            </div>
          ) : (
            rows.map((row, i) => {
              const selected = i === cursor;
              const key = row.kind === 'action' ? row.action.id : `${row.hit.origin}-${row.hit.id}`;
              return (
                <div
                  key={key}
                  id={`${listboxId}-opt-${i}`}
                  // biome-ignore lint/a11y/useSemanticElements: listbox option in a custom combobox; <option> only works inside <select>
                  role="option"
                  aria-selected={selected}
                  aria-disabled={row.kind === 'action' && row.action.disabled ? true : undefined}
                  className={`flex cursor-pointer items-center justify-between px-3 py-2 ${
                    selected ? 'bg-oxblood/30' : ''
                  } ${row.kind === 'action' && row.action.disabled ? 'opacity-40' : ''}`}
                  onMouseEnter={() => setCursor(i)}
                  onClick={() => commit(i)}
                >
                  {row.kind === 'action' ? (
                    <>
                      <span className="text-parchment">{row.action.label}</span>
                      <span className="font-mono text-ash">{row.action.hint}</span>
                    </>
                  ) : (
                    <>
                      <span className="flex items-baseline gap-3">
                        <span className="text-parchment">{row.hit.name}</span>
                        <span className="font-serif-italic text-ash">by {row.hit.author}</span>
                      </span>
                      <span className="font-mono text-ash">{row.hit.origin}</span>
                    </>
                  )}
                </div>
              );
            })
          )}
        </div>
        {remoteError && trimmedQ.length >= 2 && hits.length > 0 ? (
          <p className="border-t border-border px-4 py-2 font-mono text-xs text-crimson">
            Remote index unreachable — showing installed mods only.
          </p>
        ) : null}
      </div>
    </dialog>
  );
}
