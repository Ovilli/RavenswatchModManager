'use client';
import { Button, Card, CardContent, CardDescription, CardHeader, CardTitle, Input } from '@rsmm/ui';
import { useQuery } from '@tanstack/react-query';
import { Github, Mail } from 'lucide-react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { type FormEvent, useState } from 'react';
import { signIn, signUp } from '../../../lib/auth-client';
import { GoogleIcon, authConfigQueryKey, fetchAuthConfig } from '../../../lib/auth-ui';

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

  const config = useQuery({ queryKey: authConfigQueryKey, queryFn: fetchAuthConfig });

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
