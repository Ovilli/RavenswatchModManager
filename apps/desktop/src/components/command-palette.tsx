import { useNavigate } from '@tanstack/react-router';
import { Search } from 'lucide-react';
import { useEffect, useId, useMemo, useRef, useState } from 'react';
import { MOCK_MODS } from '../data/mock-mods';
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
  const navigate = useNavigate();
  const listboxId = useId();

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
    const needle = q.trim().toLowerCase();
    if (!needle) {
      const out: Hit[] = [];
      for (const id of installed.slice(0, 5)) {
        const m = MOCK_MODS.find((x) => x.id === id);
        if (m)
          out.push({ id: m.id, slug: m.slug, name: m.name, author: m.author, origin: 'library' });
      }
      return out;
    }
    return MOCK_MODS.filter(
      (m) =>
        m.name.toLowerCase().includes(needle) ||
        m.slug.toLowerCase().includes(needle) ||
        m.tags.some((t) => t.toLowerCase().includes(needle)),
    )
      .slice(0, 10)
      .map<Hit>((m) => ({
        id: m.id,
        slug: m.slug,
        name: m.name,
        author: m.author,
        origin: installed.includes(m.id) ? 'library' : 'remote',
      }));
  }, [q, installed]);

  if (!open) return null;

  function commit(idx: number) {
    const hit = hits[idx];
    if (!hit) return;
    setOpen(false);
    navigate({ to: '/mod/$slug', params: { slug: hit.slug } });
  }

  return (
    <div
      role="dialog"
      aria-modal="true"
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
        <ul
          id={listboxId}
          role="listbox"
          aria-label="Mod search results"
          className="max-h-[50vh] overflow-y-auto py-2"
        >
          {hits.length === 0 ? (
            <li className="font-serif-italic px-4 py-6 text-center text-ash">
              No mods match. Try a different word.
            </li>
          ) : (
            hits.map((h, i) => (
              <li
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
              </li>
            ))
          )}
        </ul>
      </div>
    </div>
  );
}

