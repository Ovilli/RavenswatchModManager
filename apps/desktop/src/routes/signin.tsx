import { createFileRoute, useNavigate } from '@tanstack/react-router';
import { LogIn, UserPlus } from 'lucide-react';
import { type FormEvent, useState } from 'react';
import { Button, CopyButton, Panel, SectionHeader } from '../components/chrome';
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
          handleAuthError(result.error, 'signup');
          return;
        }
      } else {
        const result = await signIn.email({
          email: trimmedEmail,
          password,
        });
        if (result.error) {
          handleAuthError(result.error, 'signin');
          return;
        }
      }
      navigate({ to: '/' });
    } catch (err) {
      if (err instanceof TypeError && err.message === 'Failed to fetch') {
        setError('Could not reach the server. Check your connection or try again later.');
      } else {
        setError(err instanceof Error ? err.message : 'Unexpected error.');
      }
    } finally {
      setBusy(false);
    }
  };

  // Map better-auth's typed error codes to operator-friendly copy.
  // We treat the code as the canonical signal — `error.message` from
  // the server can be terse ("Invalid email or password") or verbose
  // ("[body.name] Invalid input: …") and is not localised.
  const handleAuthError = (
    err: { code?: string; status?: number; message?: string },
    flow: Mode,
  ) => {
    const code = err.code ?? '';
    if (code === 'USER_ALREADY_EXISTS' || code === 'EMAIL_ALREADY_EXISTS') {
      setError('That email is already registered. Try signing in instead.');
      // Nudge the user toward the right tab so the next click works.
      if (flow === 'signup') setMode('signin');
      return;
    }
    if (code === 'INVALID_EMAIL_OR_PASSWORD' || err.status === 401) {
      setError('Email or password did not match an existing account.');
      return;
    }
    if (code === 'PASSWORD_TOO_SHORT' || code === 'PASSWORD_TOO_LONG') {
      setError(err.message ?? 'Password does not meet the requirements.');
      return;
    }
    if (err.status === 429) {
      setError('Too many attempts. Wait a minute and try again.');
      return;
    }
    if (err.status === 422 || code === 'VALIDATION_ERROR') {
      setError(err.message ?? 'The server rejected the form — check your inputs.');
      return;
    }
    setError(err.message ?? (flow === 'signup' ? 'Could not create account.' : 'Could not sign in.'));
  };

  const isSignup = mode === 'signup';

  return (
    <div className="mx-auto w-full max-w-md space-y-6">
      <SectionHeader
        title={isSignup ? 'Create an account' : 'Sign in'}
        subtitle={
          isSignup
            ? 'Join the rsmm index to track your library and sync your profiles.'
            : 'Welcome back, modder.'
        }
      />

      <Panel>
        <form className="space-y-4" onSubmit={onSubmit}>
          <label className="block space-y-1">
            <span className="font-mono text-xs uppercase tracking-[0.22em] text-ash">Email</span>
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
            <span className="font-mono text-xs uppercase tracking-[0.22em] text-ash">Password</span>
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
              <span className="font-mono text-xs text-ash">Minimum 8 characters.</span>
            ) : null}
          </label>

          {error ? (
            <div className="flex items-start gap-2">
              <p className="text-sm text-crimson flex-1" role="alert">
                {error}
              </p>
              <CopyButton value={error} />
            </div>
          ) : null}

          <Button type="submit" variant="primary" disabled={busy} className="w-full justify-center">
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
