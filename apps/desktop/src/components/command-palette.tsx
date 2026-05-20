import { useNavigate } from '@tanstack/react-router';
import { Search } from 'lucide-react';
import { useEffect, useMemo, useRef, useState } from 'react';
import { MOCK_MODS } from '../data/mock-mods';
import { useApp } from '../store';

interface Hit {
  id: string;
  name: string;
  author: string;
  origin: 'library' | 'remote';
}

export function CommandPalette() {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState('');
  const [cursor, setCursor] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const installed = useApp((s) => s.installed);
  const navigate = useNavigate();

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      const meta = e.metaKey || e.ctrlKey;
      if (meta && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        setOpen((o) => !o);
      } else if (e.key === 'Escape' && open) {
        setOpen(false);
      }
    }
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open]);

  useEffect(() => {
    if (open) {
      setQ('');
      setCursor(0);
      setTimeout(() => inputRef.current?.focus(), 10);
    }
  }, [open]);

  const hits = useMemo<Hit[]>(() => {
    const needle = q.trim().toLowerCase();
    if (!needle) {
      const out: Hit[] = [];
      for (const id of installed.slice(0, 5)) {
        const m = MOCK_MODS.find((x) => x.id === id);
        if (m) out.push({ id: m.id, name: m.name, author: m.author, origin: 'library' });
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
    navigate({ to: '/mod/$slug', params: { slug: hit.id } });
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center pt-[12vh] animate-fade-in"
      onClick={() => setOpen(false)}
    >
      <div className="absolute inset-0 bg-pitch/80" />
      <div
        className="grimoire-card relative w-[min(620px,90vw)] p-2"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center gap-3 border-b border-border px-3 py-2">
          <Search className="h-4 w-4 text-ash" />
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
              } else if (e.key === 'Enter') {
                e.preventDefault();
                commit(cursor);
              }
            }}
            placeholder="Search mods — installed and remote"
            className="w-full bg-transparent text-parchment placeholder:text-ash focus:outline-none"
          />
          <span className="font-mono text-ash">ESC</span>
        </div>
        <ul className="max-h-[50vh] overflow-y-auto py-2" >
          {hits.length === 0 ? (
            <li className="font-serif-italic px-4 py-6 text-center text-ash">
              No mods match. Try a different word.
            </li>
          ) : (
            hits.map((h, i) => (
              <li
                key={`${h.origin}-${h.id}`}
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
