'use client';
import { Button, Card, CardContent, CardDescription, CardHeader, CardTitle, Input } from '@rsmm/ui';
import { Mail } from 'lucide-react';
import Link from 'next/link';
import { type FormEvent, useState } from 'react';
import { authClient } from '../../../lib/auth-client';

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState(false);

  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    // The reset link in the email routes through the API, which then
    // redirects the browser to this absolute frontend URL with `?token=`.
    const redirectTo = `${window.location.origin}/auth/reset-password`;
    const res = await authClient.requestPasswordReset({ email: email.trim(), redirectTo });
    setBusy(false);
    // Always show the same confirmation regardless of whether the address
    // exists — never leak which emails have accounts.
    if (res.error) setError(res.error.message ?? 'Could not send reset email.');
    else setSent(true);
  }

  if (sent) {
    return (
      <main className="container mx-auto flex min-h-[80vh] items-center justify-center px-6 animate-page-in">
        <Card className="w-full max-w-md grimoire-card">
          <CardHeader>
            <CardTitle>Check your email</CardTitle>
            <CardDescription>
              If an account exists for <strong>{email}</strong>, a password-reset link is on its
              way. The link expires in one hour.
            </CardDescription>
          </CardHeader>
          <CardContent className="text-sm text-muted-foreground">
            <Link
              href={{ pathname: '/auth/signin' }}
              className="inline-block underline hover:text-foreground"
            >
              Back to sign in →
            </Link>
          </CardContent>
        </Card>
      </main>
    );
  }

  return (
    <main className="container mx-auto flex min-h-[80vh] items-center justify-center px-6 animate-page-in">
      <Card className="w-full max-w-md grimoire-card">
        <CardHeader>
          <CardTitle>Reset your password</CardTitle>
          <CardDescription>Enter your email and we'll send you a reset link.</CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={submit} className="space-y-3">
            <Input
              type="email"
              placeholder="email"
              value={email}
              onChange={(e) => setEmail((e.target as HTMLInputElement).value)}
              required
            />
            {error ? <p className="text-sm text-destructive">{error}</p> : null}
            <Button type="submit" disabled={busy} className="w-full">
              <Mail className="h-4 w-4" /> {busy ? 'sending…' : 'send reset link'}
            </Button>
            <p className="text-center text-sm text-muted-foreground">
              Remembered it?{' '}
              <Link className="underline hover:text-foreground" href={{ pathname: '/auth/signin' }}>
                Sign in
              </Link>
            </p>
          </form>
        </CardContent>
      </Card>
    </main>
  );
}
