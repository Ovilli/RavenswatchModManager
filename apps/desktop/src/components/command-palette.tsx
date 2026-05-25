import { useQuery } from '@tanstack/react-query';
import { useNavigate } from '@tanstack/react-router';
import { Search } from 'lucide-react';
import { useEffect, useId, useMemo, useRef, useState } from 'react';
import { api } from '../lib/api';
import { useApp } from '../store';

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

  // Remote index search runs only while the palette is open + the user
  // has typed at least 2 chars. React Query caches per `q` so repeated
  // typing doesn't hammer the API.
  const trimmedQ = q.trim();
  const { data: remoteData } = useQuery({
    queryKey: ['mods', 'palette', trimmedQ],
    queryFn: () => api.mods.list({ q: trimmedQ, limit: 10 }),
    enabled: open && trimmedQ.length >= 2,
    staleTime: 30_000,
  });

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

  if (!open) return null;

  function commit(idx: number) {
    const hit = hits[idx];
    if (!hit) return;
    setOpen(false);
    navigate({ to: '/mod/$slug', params: { slug: hit.slug } });
  }

  return (
    <dialog
      open
      aria-label="Search mods"
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
                setCursor((c) => Math.min(c + 1, hits.length - 1));
              } else if (e.key === 'ArrowUp') {
                e.preventDefault();
                setCursor((c) => Math.max(c - 1, 0));
              } else if (e.key === 'Home') {
                e.preventDefault();
                setCursor(0);
              } else if (e.key === 'End') {
                e.preventDefault();
                setCursor(Math.max(hits.length - 1, 0));
              } else if (e.key === 'Enter') {
                e.preventDefault();
                commit(cursor);
              }
            }}
            placeholder="Search mods — installed and remote"
            className="w-full bg-transparent text-parchment placeholder:text-ash focus:outline-none"
            role="combobox"
            aria-expanded={true}
            aria-controls={listboxId}
            aria-activedescendant={hits[cursor] ? `${listboxId}-opt-${cursor}` : undefined}
            aria-autocomplete="list"
          />
          <span className="font-mono text-ash">ESC</span>
        </div>
        <div
          id={listboxId}
          role="listbox"
          aria-label="Mod search results"
          className="max-h-[50vh] overflow-y-auto py-2"
        >
          {hits.length === 0 ? (
            <div className="font-serif-italic px-4 py-6 text-center text-ash">
              No mods match. Try a different word.
            </div>
          ) : (
            hits.map((h, i) => (
              <div
                key={`${h.origin}-${h.id}`}
                id={`${listboxId}-opt-${i}`}
                role="option"
                aria-selected={i === cursor}
                className={`flex cursor-pointer items-center justify-between px-3 py-2 ${
                  i === cursor ? 'bg-oxblood/30' : ''
                }`}
                onMouseEnter={() => setCursor(i)}
                onClick={() => commit(i)}
              >
                <span className="flex items-baseline gap-3">
                  <span className="text-parchment">{h.name}</span>
                  <span className="font-serif-italic text-ash">by {h.author}</span>
                </span>
                <span className="font-mono text-ash">{h.origin}</span>
              </div>
            ))
          )}
        </div>
      </div>
    </dialog>
  );
}

