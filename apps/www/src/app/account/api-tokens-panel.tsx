'use client';

import type { ApiTokenCreated, ApiTokenSummary } from '@rsmm/schemas';
import {
  Button,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  Input,
  Spinner,
} from '@rsmm/ui';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Check, Copy, KeyRound, Trash2 } from 'lucide-react';
import { useState } from 'react';
import { api } from '../../lib/api';

const EXPIRY_CHOICES = [
  { days: 30, label: '30 days' },
  { days: 90, label: '90 days' },
  { days: 180, label: '180 days' },
  { days: 365, label: '1 year' },
];

function fmtDate(iso: string | null): string {
  return iso ? new Date(iso).toLocaleDateString() : 'never';
}

function tokenState(t: ApiTokenSummary): 'active' | 'revoked' | 'expired' {
  if (t.revokedAt) return 'revoked';
  return new Date(t.expiresAt).getTime() <= Date.now() ? 'expired' : 'active';
}

/**
 * Personal API tokens for `rsmm publish`. A token can publish new versions of
 * this account's mods and nothing else; every version still has to pass the
 * malware scan before it can be downloaded. The plaintext is shown once, right
 * after creation — the server keeps only a hash.
 */
export function ApiTokensPanel() {
  const queryClient = useQueryClient();
  const [name, setName] = useState('');
  const [days, setDays] = useState(90);
  const [created, setCreated] = useState<ApiTokenCreated | null>(null);
  const [copied, setCopied] = useState(false);

  const tokens = useQuery({ queryKey: ['me', 'tokens'], queryFn: () => api.me.tokens() });

  const create = useMutation({
    mutationFn: () => api.me.createToken({ name: name.trim(), expiresInDays: days }),
    onSuccess: (token) => {
      setCreated(token);
      setCopied(false);
      setName('');
      queryClient.invalidateQueries({ queryKey: ['me', 'tokens'] });
    },
  });

  const revoke = useMutation({
    mutationFn: (id: string) => api.me.revokeToken(id),
    onSuccess: (_row, id) => {
      if (created?.id === id) setCreated(null);
      queryClient.invalidateQueries({ queryKey: ['me', 'tokens'] });
    },
  });

  const list = tokens.data?.tokens ?? [];

  return (
    <Card className="grimoire-card" id="api-tokens">
      <CardHeader>
        <CardTitle>API tokens</CardTitle>
        <CardDescription>
          Publish mods from the command line with <code>rsmm publish</code>. A token can upload new
          versions of your own mods and nothing else — it cannot change your account, and every
          version still passes the malware scan before anyone can download it. Treat it like a
          password.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {created ? (
          <div className="space-y-2 rounded border border-primary/40 bg-primary/5 p-3">
            <p className="text-sm font-medium">Copy your token now — it will not be shown again.</p>
            <div className="flex items-center gap-2">
              <code className="min-w-0 flex-1 break-all rounded bg-background/60 px-2 py-1 text-xs">
                {created.token}
              </code>
              <Button
                size="sm"
                variant="outline"
                onClick={async () => {
                  await navigator.clipboard.writeText(created.token);
                  setCopied(true);
                }}
              >
                {copied ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />}
                {copied ? 'Copied' : 'Copy'}
              </Button>
            </div>
            <p className="text-xs text-muted-foreground">
              Then run <code>rsmm publish login</code> and paste it, or set{' '}
              <code>RSMM_API_TOKEN</code>. Never pass it as a command argument.
            </p>
            <Button size="sm" variant="ghost" onClick={() => setCreated(null)}>
              I have saved it
            </Button>
          </div>
        ) : null}

        <form
          className="flex flex-wrap items-end gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            if (name.trim()) create.mutate();
          }}
        >
          <div className="flex min-w-48 flex-1 flex-col gap-1 text-xs text-muted-foreground">
            <label htmlFor="api-token-name">Name</label>
            <Input
              id="api-token-name"
              value={name}
              maxLength={64}
              placeholder="e.g. laptop, release script"
              onChange={(e) => setName((e.target as HTMLInputElement).value)}
            />
          </div>
          <label className="flex flex-col gap-1 text-xs text-muted-foreground">
            Expires after
            <select
              className="h-9 rounded-md border border-input bg-background px-2 text-sm text-foreground"
              value={days}
              onChange={(e) => setDays(Number(e.target.value))}
            >
              {EXPIRY_CHOICES.map((c) => (
                <option key={c.days} value={c.days}>
                  {c.label}
                </option>
              ))}
            </select>
          </label>
          <Button type="submit" disabled={!name.trim() || create.isPending}>
            {create.isPending ? <Spinner /> : <KeyRound className="h-4 w-4" />} Create token
          </Button>
        </form>
        {create.isError ? (
          <p className="text-xs text-destructive">{(create.error as Error).message}</p>
        ) : null}

        {tokens.isLoading ? (
          <Spinner />
        ) : list.length === 0 ? (
          <p className="text-sm text-muted-foreground">No tokens yet.</p>
        ) : (
          <ul className="divide-y divide-border rounded border border-border">
            {list.map((t) => {
              const state = tokenState(t);
              return (
                <li key={t.id} className="flex flex-wrap items-center gap-x-4 gap-y-1 px-3 py-2">
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-medium">{t.name}</p>
                    <p className="text-xs text-muted-foreground">
                      <code>{t.prefix}…</code> · created {fmtDate(t.createdAt)} · last used{' '}
                      {fmtDate(t.lastUsedAt)} ·{' '}
                      {state === 'active'
                        ? `expires ${fmtDate(t.expiresAt)}`
                        : state === 'revoked'
                          ? `revoked ${fmtDate(t.revokedAt)}`
                          : 'expired'}
                    </p>
                  </div>
                  {state === 'active' ? (
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={revoke.isPending}
                      onClick={() => {
                        if (
                          window.confirm(`Revoke "${t.name}"? Anything using it stops working.`)
                        ) {
                          revoke.mutate(t.id);
                        }
                      }}
                    >
                      <Trash2 className="h-4 w-4" /> Revoke
                    </Button>
                  ) : null}
                </li>
              );
            })}
          </ul>
        )}
        {revoke.isError ? (
          <p className="text-xs text-destructive">{(revoke.error as Error).message}</p>
        ) : null}
      </CardContent>
    </Card>
  );
}
