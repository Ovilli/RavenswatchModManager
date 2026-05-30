'use client';
import { Button, Card, CardContent, CardDescription, CardHeader, CardTitle, Input } from '@rsmm/ui';
import { KeyRound } from 'lucide-react';
import type { Route } from 'next';
import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';
import { type FormEvent, Suspense, useState } from 'react';
import { authClient } from '../../../lib/auth-client';

export default function ResetPasswordPage() {
  return (
    <Suspense
      fallback={
        <main className="container mx-auto px-6 py-16 text-sm text-muted-foreground">Loading…</main>
      }
    >
      <ResetPasswordInner />
    </Suspense>
  );
}

function ResetPasswordInner() {
  const router = useRouter();
  const search = useSearchParams();
  const token = search.get('token');
  // better-auth redirects here with `?error=INVALID_TOKEN` when the link
  // is expired or already used.
  const linkError = search.get('error');

  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);

  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setError(null);
    if (password !== confirm) {
      setError('Passwords do not match.');
      return;
    }
    if (!token) {
      setError('Missing reset token. Request a new link.');
      return;
    }
    setBusy(true);
    const res = await authClient.resetPassword({ newPassword: password, token });
    setBusy(false);
    if (res.error) setError(res.error.message ?? 'Could not reset password.');
    else setDone(true);
  }

  if (linkError || (!token && !done)) {
    return (
      <main className="container mx-auto flex min-h-[80vh] items-center justify-center px-6 animate-page-in">
        <Card className="w-full max-w-md grimoire-card">
          <CardHeader>
            <CardTitle>Link expired or invalid</CardTitle>
            <CardDescription>
              This password-reset link is no longer valid. Request a fresh one.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Link
              href={{ pathname: '/auth/forgot-password' }}
              className="inline-block underline hover:text-foreground"
            >
              Request a new link →
            </Link>
          </CardContent>
        </Card>
      </main>
    );
  }

  if (done) {
    return (
      <main className="container mx-auto flex min-h-[80vh] items-center justify-center px-6 animate-page-in">
        <Card className="w-full max-w-md grimoire-card">
          <CardHeader>
            <CardTitle>Password updated</CardTitle>
            <CardDescription>You can now sign in with your new password.</CardDescription>
          </CardHeader>
          <CardContent>
            <Button onClick={() => router.push('/auth/signin' as Route)} className="w-full">
              Go to sign in
            </Button>
          </CardContent>
        </Card>
      </main>
    );
  }

  return (
    <main className="container mx-auto flex min-h-[80vh] items-center justify-center px-6 animate-page-in">
      <Card className="w-full max-w-md grimoire-card">
        <CardHeader>
          <CardTitle>Set a new password</CardTitle>
          <CardDescription>Pick a password you don't use anywhere else.</CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={submit} className="space-y-3">
            <Input
              type="password"
              placeholder="new password (min 8 chars)"
              value={password}
              onChange={(e) => setPassword((e.target as HTMLInputElement).value)}
              required
              minLength={8}
            />
            <Input
              type="password"
              placeholder="confirm new password"
              value={confirm}
              onChange={(e) => setConfirm((e.target as HTMLInputElement).value)}
              required
              minLength={8}
            />
            {error ? <p className="text-sm text-destructive">{error}</p> : null}
            <Button type="submit" disabled={busy} className="w-full">
              <KeyRound className="h-4 w-4" /> {busy ? 'updating…' : 'update password'}
            </Button>
          </form>
        </CardContent>
      </Card>
    </main>
  );
}
