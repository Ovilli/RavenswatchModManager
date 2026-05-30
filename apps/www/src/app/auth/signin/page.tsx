'use client';
import { Button, Card, CardContent, CardDescription, CardHeader, CardTitle, Input } from '@rsmm/ui';
import { useQuery } from '@tanstack/react-query';
import { Github, Mail } from 'lucide-react';
import type { Route } from 'next';
import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';
import { type FormEvent, Suspense, useState } from 'react';
import { signIn } from '../../../lib/auth-client';
import { GoogleIcon, authConfigQueryKey, fetchAuthConfig } from '../../../lib/auth-ui';

export default function SignInPage() {
  return (
    <Suspense
      fallback={
        <main className="container mx-auto px-6 py-16 text-sm text-muted-foreground">Loading…</main>
      }
    >
      <SignInInner />
    </Suspense>
  );
}

function SignInInner() {
  const router = useRouter();
  const search = useSearchParams();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const config = useQuery({ queryKey: authConfigQueryKey, queryFn: fetchAuthConfig });
  const callbackURL = search.get('next') ?? '/';

  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    const res = await signIn.email({ email, password, callbackURL });
    setBusy(false);
    if (res.error) setError(res.error.message ?? 'sign-in failed');
    else router.push(callbackURL as Route);
  }

  async function social(provider: 'google' | 'github') {
    setError(null);
    setBusy(true);
    const res = await signIn.social({ provider, callbackURL });
    if (res.error) {
      setBusy(false);
      setError(res.error.message ?? `${provider} sign-in failed`);
    }
  }

  const hasSocial = !!(config.data?.providers.google || config.data?.providers.github);

  return (
    <main className="container mx-auto flex min-h-[80vh] items-center justify-center px-6 animate-page-in">
      <Card className="w-full max-w-md grimoire-card">
        <CardHeader>
          <CardTitle>Sign in</CardTitle>
          <CardDescription>Welcome back.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {hasSocial ? (
            <div className="space-y-2">
              {config.data?.providers.google ? (
                <Button
                  type="button"
                  variant="outline"
                  className="w-full"
                  disabled={busy}
                  onClick={() => social('google')}
                >
                  <GoogleIcon /> Continue with Google
                </Button>
              ) : null}
              {config.data?.providers.github ? (
                <Button
                  type="button"
                  variant="outline"
                  className="w-full"
                  disabled={busy}
                  onClick={() => social('github')}
                >
                  <Github className="h-4 w-4" /> Continue with GitHub
                </Button>
              ) : null}
              <div className="flex items-center gap-3 pt-1 text-xs text-muted-foreground">
                <div className="h-px flex-1 bg-border" />
                <span>or</span>
                <div className="h-px flex-1 bg-border" />
              </div>
            </div>
          ) : null}

          <form onSubmit={submit} className="space-y-3">
            <Input
              type="email"
              placeholder="email"
              value={email}
              onChange={(e) => setEmail((e.target as HTMLInputElement).value)}
              required
            />
            <Input
              type="password"
              placeholder="password"
              value={password}
              onChange={(e) => setPassword((e.target as HTMLInputElement).value)}
              required
              minLength={8}
            />
            {error ? <p className="text-sm text-destructive">{error}</p> : null}
            <div className="text-right">
              <Link
                className="text-sm text-muted-foreground underline hover:text-foreground"
                href={{ pathname: '/auth/forgot-password' }}
              >
                Forgot password?
              </Link>
            </div>
            <Button type="submit" disabled={busy} className="w-full">
              <Mail className="h-4 w-4" /> {busy ? 'signing in…' : 'sign in with email'}
            </Button>
            <p className="text-center text-sm text-muted-foreground">
              No account?{' '}
              <Link className="underline hover:text-foreground" href={{ pathname: '/auth/signup' }}>
                Sign up
              </Link>
            </p>
          </form>
        </CardContent>
      </Card>
    </main>
  );
}
