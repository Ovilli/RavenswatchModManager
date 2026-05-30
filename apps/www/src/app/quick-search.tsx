'use client';

import { Search } from 'lucide-react';
import { useRouter } from 'next/navigation';
import { useState } from 'react';

export function QuickSearch() {
  const router = useRouter();
  const [q, setQ] = useState('');

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        const trimmed = q.trim();
        if (trimmed) router.push(`/registry?q=${encodeURIComponent(trimmed)}`);
        else router.push('/registry');
      }}
      className="relative"
    >
      <Search
        className="absolute left-4 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground"
        aria-hidden
      />
      <input
        type="search"
        value={q}
        onChange={(e) => setQ(e.target.value)}
        placeholder="Search mods by name, author, or keyword…"
        aria-label="Search mods"
        className="w-full rounded-xl border border-border/60 bg-card/80 px-11 py-3.5 text-sm text-foreground placeholder-muted-foreground backdrop-blur-sm transition-colors focus:border-gilt/50 focus:outline-none focus:ring-1 focus:ring-gilt/20"
      />
      <button
        type="submit"
        className="absolute right-2 top-1/2 -translate-y-1/2 rounded-lg bg-crimson px-3 py-1.5 text-xs font-medium text-white transition-colors hover:bg-crimson/90"
      >
        Search
      </button>
    </form>
  );
}
