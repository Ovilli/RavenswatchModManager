'use client';
import { Button, Card, CardContent, CardDescription, CardHeader, CardTitle, Input } from '@rsmm/ui';
import { useRouter } from 'next/navigation';
import { useState, type FormEvent } from 'react';
import { signIn } from '../../../lib/auth-client';

export default function SignInPage() {
  const router = useRouter();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    const res = await signIn.email({ email, password });
    setBusy(false);
    if (res.error) setError(res.error.message ?? 'sign-in failed');
    else router.push('/');
  }

  return (
    <main className="container mx-auto flex min-h-[80vh] items-center justify-center px-6">
      <Card className="w-full max-w-md">
        <CardHeader>
          <CardTitle>Sign in</CardTitle>
          <CardDescription>Welcome back.</CardDescription>
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
            <Input
              type="password"
              placeholder="password"
              value={password}
              onChange={(e) => setPassword((e.target as HTMLInputElement).value)}
              required
              minLength={8}
            />
            {error ? <p className="text-sm text-destructive">{error}</p> : null}
            <Button type="submit" disabled={busy} className="w-full">
              {busy ? 'signing in…' : 'sign in'}
            </Button>
            <p className="text-center text-sm text-muted-foreground">
              No account? <a className="underline" href="/auth/signup">Sign up</a>
            </p>
          </form>
        </CardContent>
      </Card>
    </main>
  );
}
