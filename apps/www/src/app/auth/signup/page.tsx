'use client';
import { Button, Card, CardContent, CardDescription, CardHeader, CardTitle, Input } from '@rsmm/ui';
import { useRouter } from 'next/navigation';
import { useState, type FormEvent } from 'react';
import { signUp } from '../../../lib/auth-client';

export default function SignUpPage() {
  const router = useRouter();
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    const res = await signUp.email({ email, password, name });
    setBusy(false);
    if (res.error) setError(res.error.message ?? 'sign-up failed');
    else router.push('/');
  }

  return (
    <main className="container mx-auto flex min-h-[80vh] items-center justify-center px-6">
      <Card className="w-full max-w-md">
        <CardHeader>
          <CardTitle>Create account</CardTitle>
          <CardDescription>Publish mods + sync your library.</CardDescription>
        </CardHeader>
        <CardContent>
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
              {busy ? 'creating…' : 'sign up'}
            </Button>
            <p className="text-center text-sm text-muted-foreground">
              Have an account? <a className="underline" href="/auth/signin">Sign in</a>
            </p>
          </form>
        </CardContent>
      </Card>
    </main>
  );
}
