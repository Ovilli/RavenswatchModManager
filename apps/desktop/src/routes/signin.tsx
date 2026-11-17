import { useQuery } from '@tanstack/react-query';
import { createFileRoute, useNavigate } from '@tanstack/react-router';
import { openUrl } from '@tauri-apps/plugin-opener';
import { Github, LogIn, UserPlus } from 'lucide-react';
import { type FormEvent, useEffect, useState } from 'react';
import { Button, CopyButton, Panel, SectionHeader } from '../components/chrome';
import { describeApiError } from '../lib/api';
import { getApiUrl } from '../lib/api-url';
import { authClient, signIn, signUp } from '../lib/auth-client';
import { onDesktopAuthFailure, takeDesktopAuthFailure } from '../lib/desktop-auth';
import { useT } from '../lib/i18n-react';

export const Route = createFileRoute('/signin')({
  component: SignInPage,
});

type Mode = 'signin' | 'signup';

interface AuthConfig {
  providers: { google: boolean; discord?: boolean; github: boolean };
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

function DiscordIcon() {
  return (
    <svg viewBox="0 0 24 24" className="h-4 w-4" aria-hidden="true">
      <title>Discord</title>
      <path
        fill="#5865F2"
        d="M20.317 4.37a19.79 19.79 0 0 0-4.885-1.515.074.074 0 0 0-.079.037c-.21.375-.444.865-.608 1.25a18.27 18.27 0 0 0-5.487 0 12.64 12.64 0 0 0-.617-1.25.077.077 0 0 0-.079-.037A19.74 19.74 0 0 0 3.677 4.37a.07.07 0 0 0-.032.028C.533 9.046-.32 13.58.099 18.058a.082.082 0 0 0 .031.056 19.9 19.9 0 0 0 5.993 3.03.078.078 0 0 0 .084-.028c.462-.63.874-1.295 1.226-1.994a.076.076 0 0 0-.041-.106 13.1 13.1 0 0 1-1.872-.892.077.077 0 0 1-.008-.128c.126-.094.252-.192.372-.291a.074.074 0 0 1 .078-.01c3.928 1.793 8.18 1.793 12.061 0a.074.074 0 0 1 .079.01c.12.098.246.198.373.292a.077.077 0 0 1-.007.127 12.3 12.3 0 0 1-1.873.892.077.077 0 0 0-.041.107c.36.698.772 1.362 1.225 1.993a.076.076 0 0 0 .084.029 19.84 19.84 0 0 0 6.002-3.03.077.077 0 0 0 .032-.054c.5-5.177-.838-9.674-3.549-13.66a.061.061 0 0 0-.031-.03zM8.02 15.331c-1.182 0-2.157-1.085-2.157-2.419 0-1.333.956-2.419 2.157-2.419 1.21 0 2.176 1.096 2.157 2.42 0 1.333-.956 2.418-2.157 2.418zm7.975 0c-1.183 0-2.157-1.085-2.157-2.419 0-1.333.955-2.419 2.157-2.419 1.21 0 2.176 1.096 2.157 2.42 0 1.333-.946 2.418-2.157 2.418z"
      />
    </svg>
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

function SignInPage() {
  const t = useT();
  const navigate = useNavigate();
  const [mode, setMode] = useState<Mode>('signin');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const config = useQuery({ queryKey: ['auth-config'], queryFn: fetchAuthConfig });
  const hasSocial = !!(
    config.data?.providers.google ||
    config.data?.providers.discord ||
    config.data?.providers.github
  );

  // Surface deep-link relay failures reported by main.tsx: on mount for the
  // cold-start case (the failure landed before this page existed), via the
  // event for the warm case (user is sitting on this page when the deep link
  // comes back broken — the browser flow ends silently otherwise).
  useEffect(() => {
    const show = () => {
      const message = takeDesktopAuthFailure();
      if (message) setError(message);
    };
    show();
    return onDesktopAuthFailure(show);
  }, []);

  // Kicks off OAuth entirely in the system browser via the desktop-auth relay.
  // The browser completes the flow against the provider's normal callback (so
  // Google — which rejects redirect URIs with query strings — works too), then
  // deep-links a one-time token back into the app, where the listener in
  // main.tsx exchanges it for a session. Nothing to await here beyond launch.
  // The `app` nonce binds the eventual deep link to THIS launch: main.tsx
  // rejects tokens whose nonce doesn't match (login-CSRF guard — the relay
  // callback can't rely on the browser state cookie, see apps/api desktop-auth).
  const social = async (provider: 'google' | 'discord' | 'github') => {
    setError(null);
    setBusy(true);
    try {
      const nonce = crypto.randomUUID();
      // localStorage (not sessionStorage): the deep link may cold-start a
      // fresh app process, which must still see the nonce.
      localStorage.setItem('rsmm.desktopAuthNonce', nonce);
      const base = getApiUrl().replace(/\/+$/, '');
      await openUrl(`${base}/api/desktop-auth/start?provider=${provider}&app=${nonce}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : t('{provider} sign-in failed', { provider }));
    } finally {
      // Re-enable the buttons: the deep-link handler navigates away on success;
      // if the user cancels in the browser they land back here able to retry.
      setBusy(false);
    }
  };

  const onSubmit = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    setError(null);
    const trimmedEmail = email.trim().toLowerCase();
    if (!trimmedEmail || !password) {
      setError(t('Email and password are required.'));
      return;
    }
    if (password.length < 8) {
      setError(t('Password must be at least 8 characters.'));
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
          setError(t('Account created. Check your email to verify, then sign in.'));
          setMode('signin');
          return;
        }
        setError(t('Signed in, but the session could not be loaded. Try again.'));
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
        setError(err instanceof Error ? err.message : t('Unexpected error.'));
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
      setError(t('That email is already registered. Try signing in instead.'));
      // Nudge the user toward the right tab so the next click works.
      if (flow === 'signup') setMode('signin');
      return;
    }
    if (code === 'INVALID_EMAIL_OR_PASSWORD' || err.status === 401) {
      setError(t('Email or password did not match an existing account.'));
      return;
    }
    if (code === 'PASSWORD_TOO_SHORT' || code === 'PASSWORD_TOO_LONG') {
      setError(err.message ?? t('Password does not meet the requirements.'));
      return;
    }
    if (err.status === 429) {
      setError(t('Too many attempts. Wait a minute and try again.'));
      return;
    }
    if (err.status === 422 || code === 'VALIDATION_ERROR') {
      setError(err.message ?? t('The server rejected the form — check your inputs.'));
      return;
    }
    setError(
      err.message ?? (flow === 'signup' ? t('Could not create account.') : t('Could not sign in.')),
    );
  };

  const isSignup = mode === 'signup';

  return (
    <div className="mx-auto w-full max-w-md space-y-6">
      <SectionHeader
        title={isSignup ? t('Create an account') : t('Sign in')}
        subtitle={
          isSignup
            ? t('Join the rsmm index to track your library and sync your profiles.')
            : t('Welcome back, modder.')
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
                <GoogleIcon /> {t('Continue with Google')}
              </Button>
            ) : null}
            {config.data?.providers.discord ? (
              <Button
                type="button"
                variant="default"
                disabled={busy}
                onClick={() => social('discord')}
                className="w-full justify-center"
              >
                <DiscordIcon /> {t('Continue with Discord')}
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
                <Github className="h-4 w-4" /> {t('Continue with GitHub')}
              </Button>
            ) : null}
            <div className="flex items-center gap-3 pt-1 font-mono text-xs text-ash">
              <div className="h-px flex-1 bg-ash/30" />
              <span>{t('or')}</span>
              <div className="h-px flex-1 bg-ash/30" />
            </div>
          </div>
        ) : null}
        <form className="space-y-4" onSubmit={onSubmit}>
          <label className="block space-y-1">
            <span className="font-mono text-xs text-ash">{t('Email')}</span>
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
            <span className="font-mono text-xs text-ash">{t('Password')}</span>
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
              <span className="font-mono text-xs text-ash">{t('Minimum 8 characters.')}</span>
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
                {busy ? t('Creating…') : t('Create account')}
              </>
            ) : (
              <>
                <LogIn className="h-4 w-4" />
                {busy ? t('Signing in…') : t('Sign in')}
              </>
            )}
          </Button>
        </form>
      </Panel>

      <p className="font-serif-italic text-center text-ash">
        {isSignup ? t('Already have an account?') : t('No account yet?')}{' '}
        <button
          type="button"
          onClick={() => {
            setMode(isSignup ? 'signin' : 'signup');
            setError(null);
          }}
          className="text-gilt underline-offset-2 hover:underline"
        >
          {isSignup ? t('Sign in.') : t('Create one.')}
        </button>
      </p>
    </div>
  );
}
