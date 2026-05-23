'use client';
import { Button, Card, CardContent, CardDescription, CardHeader, CardTitle, Input } from '@rsmm/ui';
import { useQuery } from '@tanstack/react-query';
import { Github, Mail } from 'lucide-react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useState, type FormEvent } from 'react';
import { getApiUrl } from '../../../lib/api-url';
import { signIn, signUp } from '../../../lib/auth-client';

interface AuthConfig {
  providers: { google: boolean; github: boolean };
}

async function fetchAuthConfig(): Promise<AuthConfig> {
  const res = await fetch(`${getApiUrl().replace(/\/+$/, '')}/api/auth-config`, {
    credentials: 'include',
  });
  return (await res.json()) as AuthConfig;
}

export default function SignUpPage() {
  const router = useRouter();
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  // Becomes true once the API confirms signup but the user still needs
  // to verify their email. We swap the form for a "check your inbox"
  // screen in that case.
  const [awaitingVerify, setAwaitingVerify] = useState<string | null>(null);

  const config = useQuery({ queryKey: ['auth-config'], queryFn: fetchAuthConfig });

  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    const res = await signUp.email({ email, password, name });
    setBusy(false);
    if (res.error) {
      setError(res.error.message ?? 'sign-up failed');
      return;
    }
    // If the server has SMTP wired up, requireEmailVerification is on
    // and the user has NO session until they click the link. Show the
    // landing screen instead of trying to navigate.
    if (!res.data?.user || !('emailVerified' in res.data.user) || !res.data.user.emailVerified) {
      setAwaitingVerify(email);
      return;
    }
    router.push('/');
  }

  async function social(provider: 'google' | 'github') {
    setError(null);
    setBusy(true);
    const res = await signIn.social({ provider, callbackURL: '/' });
    if (res.error) {
      setBusy(false);
      setError(res.error.message ?? `${provider} sign-up failed`);
    }
  }

  if (awaitingVerify) {
    return (
      <main className="container mx-auto flex min-h-[80vh] items-center justify-center px-6 animate-page-in">
        <Card className="w-full max-w-md grimoire-card">
          <CardHeader>
            <CardTitle>Check your email</CardTitle>
            <CardDescription>
              We sent a verification link to <strong>{awaitingVerify}</strong>. Click it to finish
              creating your account.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-3 text-sm text-muted-foreground">
            <p>
              The link expires in one hour. If you don't see the email, check your spam folder or
              ask for a fresh link from the sign-in page.
            </p>
            <Link
              href={{ pathname: '/auth/signin' }}
              className="inline-block underline hover:text-foreground"
            >
              Go to sign in →
            </Link>
          </CardContent>
        </Card>
      </main>
    );
  }

  const hasSocial = !!(config.data?.providers.google || config.data?.providers.github);

  return (
    <main className="container mx-auto flex min-h-[80vh] items-center justify-center px-6 animate-page-in">
      <Card className="w-full max-w-md grimoire-card">
        <CardHeader>
          <CardTitle>Create account</CardTitle>
          <CardDescription>Publish mods + sync your library.</CardDescription>
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
              type="text"
              placeholder="display name"
              value={name}
              onChange={(e) => setName((e.target as HTMLInputElement).value)}
              required
              minLength={2}
              maxLength={64}
            />
            <Input
              type="email"
              placeholder="email"
              value={email}
              onChange={(e) => setEmail((e.target as HTMLInputElement).value)}
              required
            />
            <Input
              type="password"
              placeholder="password (min 8 chars)"
              value={password}
              onChange={(e) => setPassword((e.target as HTMLInputElement).value)}
              required
              minLength={8}
            />
            {error ? <p className="text-sm text-destructive">{error}</p> : null}
            <Button type="submit" disabled={busy} className="w-full">
              <Mail className="h-4 w-4" /> {busy ? 'creating…' : 'sign up with email'}
            </Button>
            <p className="text-center text-sm text-muted-foreground">
              Have an account?{' '}
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

function GoogleIcon() {
  return (
    <svg viewBox="0 0 24 24" className="h-4 w-4" aria-hidden="true">
      <title>Google</title>
      <path
        fill="#4285F4"
        d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"
      />
      <path
        fill="#34A853"
        d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.99.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84A11 11 0 0 0 12 23z"
      />
      <path
        fill="#FBBC05"
        d="M5.84 14.1A6.6 6.6 0 0 1 5.49 12c0-.73.13-1.44.35-2.1V7.06H2.18a11 11 0 0 0 0 9.88l3.66-2.84z"
      />
      <path
        fill="#EA4335"
        d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.06l3.66 2.84C6.71 7.31 9.14 5.38 12 5.38z"
      />
    </svg>
  );
}
