import { createFileRoute, useNavigate } from '@tanstack/react-router';
import { LogIn, UserPlus } from 'lucide-react';
import { useState, type FormEvent } from 'react';
import { Button, Panel, SectionHeader } from '../components/chrome';
import { signIn, signUp } from '../lib/auth-client';

export const Route = createFileRoute('/signin')({
  component: SignInPage,
});

type Mode = 'signin' | 'signup';

function SignInPage() {
  const navigate = useNavigate();
  const [mode, setMode] = useState<Mode>('signin');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const onSubmit = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    setError(null);
    const trimmedEmail = email.trim().toLowerCase();
    if (!trimmedEmail || !password) {
      setError('Email and password are required.');
      return;
    }
    if (password.length < 8) {
      setError('Password must be at least 8 characters.');
      return;
    }
    setBusy(true);
    try {
      if (mode === 'signup') {
        const result = await signUp.email({
          email: trimmedEmail,
          password,
          name: trimmedEmail.split('@')[0] ?? trimmedEmail,
        });
        if (result.error) {
          setError(result.error.message ?? 'Could not create account.');
          return;
        }
      } else {
        const result = await signIn.email({
          email: trimmedEmail,
          password,
        });
        if (result.error) {
          setError(result.error.message ?? 'Could not sign in.');
          return;
        }
      }
      navigate({ to: '/' });
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unexpected error.');
    } finally {
      setBusy(false);
    }
  };

  const isSignup = mode === 'signup';

  return (
    <div className="mx-auto w-full max-w-md space-y-6">
      <SectionHeader
        title={isSignup ? 'Create an account' : 'Sign in'}
        subtitle={
          isSignup
            ? 'Join the rsmm index to upload mods and track your library.'
            : 'Welcome back, modder.'
        }
      />

      <Panel>
        <form className="space-y-4" onSubmit={onSubmit}>
          <label className="block space-y-1">
            <span className="font-mono text-xs uppercase tracking-[0.22em] text-ash">
              Email
            </span>
            <input
              type="email"
              autoComplete="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="input-grim"
              disabled={busy}
            />
          </label>

          <label className="block space-y-1">
            <span className="font-mono text-xs uppercase tracking-[0.22em] text-ash">
              Password
            </span>
            <input
              type="password"
              autoComplete={isSignup ? 'new-password' : 'current-password'}
              required
              minLength={8}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="input-grim"
              disabled={busy}
            />
            {isSignup ? (
              <span className="font-mono text-xs text-ash">
                Minimum 8 characters.
              </span>
            ) : null}
          </label>

          {error ? (
            <p className="text-sm text-crimson" role="alert">
              {error}
            </p>
          ) : null}

          <Button
            type="submit"
            variant="primary"
            disabled={busy}
            className="w-full justify-center"
          >
            {isSignup ? (
              <>
                <UserPlus className="h-4 w-4" />
                {busy ? 'Creating…' : 'Create account'}
              </>
            ) : (
              <>
                <LogIn className="h-4 w-4" />
                {busy ? 'Signing in…' : 'Sign in'}
              </>
            )}
          </Button>
        </form>
      </Panel>

      <p className="font-serif-italic text-center text-ash">
        {isSignup ? 'Already have an account?' : 'No account yet?'}{' '}
        <button
          type="button"
          onClick={() => {
            setMode(isSignup ? 'signin' : 'signup');
            setError(null);
          }}
          className="text-gilt underline-offset-2 hover:underline"
        >
          {isSignup ? 'Sign in.' : 'Create one.'}
        </button>
      </p>
    </div>
  );
}
