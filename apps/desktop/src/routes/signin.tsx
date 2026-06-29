import { signInSocial } from '@daveyplate/better-auth-tauri';
import { useQuery } from '@tanstack/react-query';
import { createFileRoute, useNavigate } from '@tanstack/react-router';
import { Github, LogIn, UserPlus } from 'lucide-react';
import { type FormEvent, useState } from 'react';
import { Button, CopyButton, Panel, SectionHeader } from '../components/chrome';
import { describeApiError } from '../lib/api';
import { getApiUrl } from '../lib/api-url';
import { authClient, signIn, signUp } from '../lib/auth-client';

export const Route = createFileRoute('/signin')({
  component: SignInPage,
});

type Mode = 'signin' | 'signup';

interface AuthConfig {
  providers: { google: boolean; github: boolean };
}

/** Which social providers the API has credentials for. Mirrors the web
 * app's /api/auth-config gate so buttons only show when usable. */
async function fetchAuthConfig(): Promise<AuthConfig> {
  const res = await fetch(`${getApiUrl().replace(/\/+$/, '')}/api/auth-config`, {
    credentials: 'include',
  });
  if (!res.ok) throw new Error(`auth-config ${res.status}`);
  return res.json();
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

function SignInPage() {
  const navigate = useNavigate();
  const [mode, setMode] = useState<Mode>('signin');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const config = useQuery({ queryKey: ['auth-config'], queryFn: fetchAuthConfig });
  const hasSocial = !!(config.data?.providers.google || config.data?.providers.github);

  // Kicks off OAuth in the system browser. The API redirects back into the
  // app via the rsmm:// deep link; the listener in main.tsx finalizes the
  // session, so there's nothing to await here beyond launch errors.
  const social = async (provider: 'google' | 'github') => {
    setError(null);
    setBusy(true);
    try {
      await signInSocial({ authClient, provider });
    } catch (err) {
      setBusy(false);
      setError(err instanceof Error ? err.message : `${provider} sign-in failed`);
    }
  };

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
      const authResult =
        mode === 'signup'
          ? await signUp.email({
              email: trimmedEmail,
              password,
              name: trimmedEmail.split('@')[0] ?? trimmedEmail,
            })
          : await signIn.email({
              email: trimmedEmail,
              password,
            });
      if (authResult.error) {
        handleAuthError(authResult.error, mode);
        return;
      }
      // Refresh session cache (cookie + local storage) before leaving the page.
      const session = await authClient.getSession({ query: { disableCookieCache: true } });
      if (!session.data?.user) {
        if (mode === 'signup') {
          setError('Account created. Check your email to verify, then sign in.');
          setMode('signin');
          return;
        }
        setError('Signed in, but the session could not be loaded. Try again.');
        return;
      }
      navigate({ to: '/' });
    } catch (err) {
      // A TypeError from fetch ("Failed to fetch" / "Load failed") means
      // the request never reached the server — offline, or blocked by
      // CSP connect-src / API CORS. describeApiError spells that out.
      if (err instanceof TypeError) {
        console.error('[signin] auth request blocked', err);
        setError(describeApiError(err));
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
    setError(
      err.message ?? (flow === 'signup' ? 'Could not create account.' : 'Could not sign in.'),
    );
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
        {hasSocial ? (
          <div className="mb-4 space-y-2">
            {config.data?.providers.google ? (
              <Button
                type="button"
                variant="default"
                disabled={busy}
                onClick={() => social('google')}
                className="w-full justify-center"
              >
                <GoogleIcon /> Continue with Google
              </Button>
            ) : null}
            {config.data?.providers.github ? (
              <Button
                type="button"
                variant="default"
                disabled={busy}
                onClick={() => social('github')}
                className="w-full justify-center"
              >
                <Github className="h-4 w-4" /> Continue with GitHub
              </Button>
            ) : null}
            <div className="flex items-center gap-3 pt-1 font-mono text-xs uppercase tracking-[0.18em] text-ash">
              <div className="h-px flex-1 bg-ash/30" />
              <span>or</span>
              <div className="h-px flex-1 bg-ash/30" />
            </div>
          </div>
        ) : null}
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
