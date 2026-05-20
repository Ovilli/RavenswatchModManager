'use client';
import { Badge, Card, CardContent, CardDescription, CardHeader, CardTitle, Input, Spinner } from '@rsmm/ui';
import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { api } from '../../lib/api';

export default function RegistryPage() {
  const [q, setQ] = useState('');
  const list = useQuery({
    queryKey: ['registry', q],
    queryFn: () => api.mods.list({ q: q || undefined, limit: 48 }),
  });

  return (
    <main className="relative overflow-hidden animate-page-in">
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_top_left,hsl(var(--crimson)/0.08),transparent_50%)]" />
      <div className="relative container mx-auto space-y-6 px-6 py-12">
        <header>
          <h1 className="text-4xl font-bold tracking-tight">Registry</h1>
          <p className="text-sm text-muted-foreground">Community-published mods.</p>
        </header>

        <Input
          placeholder="Search by name or slug…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />

        {list.isLoading ? (
          <div className="flex items-center justify-center py-16">
            <Spinner />
          </div>
        ) : list.isError ? (
          <p className="text-sm text-destructive">Cannot reach API ({String(list.error)})</p>
        ) : list.data && list.data.items.length === 0 ? (
          <p className="text-sm text-muted-foreground">No mods yet. Be the first to publish.</p>
        ) : (
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
            {list.data?.items.map((m) => (
              <Card key={m.id} className="grimoire-card">
                <CardHeader>
                  <div className="flex items-center justify-between gap-2">
                    <CardTitle>{m.name}</CardTitle>
                    {m.latestVersion ? <Badge variant="outline">v{m.latestVersion}</Badge> : null}
                  </div>
                  <CardDescription>{m.slug}</CardDescription>
                </CardHeader>
                {m.summary ? (
                  <CardContent className="text-sm text-muted-foreground">{m.summary}</CardContent>
                ) : null}
              </Card>
            ))}
          </div>
        )}
      </div>
    </main>
  );
}
