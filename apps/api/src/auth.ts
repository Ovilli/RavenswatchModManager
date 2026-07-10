import { getDb, schema } from '@rsmm/db';
import { betterAuth } from 'better-auth';
import { drizzleAdapter } from 'better-auth/adapters/drizzle';
import { createAuthMiddleware } from 'better-auth/api';
import { oneTimeToken } from 'better-auth/plugins/one-time-token';
import { env, githubConfigured, googleConfigured, isProduction, smtpConfigured } from './env.js';
import { errString, log } from './logger.js';
import {
  changeEmailTemplate,
  resetPasswordTemplate,
  sendMail,
  verifyEmailTemplate,
} from './mailer.js';

const socialProviders: {
  google?: { clientId: string; clientSecret: string };
  github?: { clientId: string; clientSecret: string };
} = {};
if (googleConfigured()) {
  socialProviders.google = {
    clientId: env.google.clientId,
    clientSecret: env.google.clientSecret,
  };
}
if (githubConfigured()) {
  socialProviders.github = {
    clientId: env.github.clientId,
    clientSecret: env.github.clientSecret,
  };
}

export const auth = betterAuth({
  baseURL: env.betterAuthUrl,
  secret: env.betterAuthSecret,
  trustedOrigins: env.trustedOrigins,
  // one-time-token backs the desktop OAuth relay: the browser completes the
  // whole OAuth (normal registered callback — Google-compatible, no query
  // string) and lands on /api/desktop-auth/complete, which mints a short-lived
  // token the app exchanges for its own session cookie. See routes/desktop-auth.ts.
  // Web-safe: this plugin never touches socialProviders (unlike the removed
  // @daveyplate/better-auth-tauri server plugin that broke web state checks).
  plugins: [oneTimeToken({ expiresIn: 3 })],
  database: drizzleAdapter(getDb(), {
    provider: 'pg',
    schema: {
      user: schema.users,
      session: schema.sessions,
      account: schema.accounts,
      verification: schema.verifications,
    },
  }),
  socialProviders,
  // NOTE: we deliberately DON'T use the @daveyplate/better-auth-tauri server
  // plugin. Its `before` hook mutated the shared socialProviders redirectURI
  // per-request (breaking web OAuth state), and its whole mechanism smuggles an
  // `rsmm://` marker through the OAuth redirect_uri query string — which Google
  // rejects (redirect URIs can't contain a query), so it only ever works for
  // GitHub. Desktop OAuth instead goes through the browser-side relay in
  // routes/desktop-auth.ts + the oneTimeToken plugin above, which works for all
  // providers and leaves the web flow completely untouched.
  emailAndPassword: {
    enabled: true,
    autoSignIn: !isProduction && !smtpConfigured(),
    // Production must not silently allow unverified accounts when mail is
    // misconfigured. Dev without SMTP can still auto-sign-in locally.
    requireEmailVerification: isProduction || smtpConfigured(),
    sendResetPassword: async ({ user, url }) => {
      const t = resetPasswordTemplate({ name: user.name, url });
      try {
        await sendMail({ to: user.email, subject: t.subject, text: t.text, html: t.html });
      } catch (err) {
        log.error('failed to send password-reset email', { err: errString(err) });
      }
    },
  },
  emailVerification: {
    sendOnSignUp: true,
    autoSignInAfterVerification: true,
    sendVerificationEmail: async ({ user, url }) => {
      const t = verifyEmailTemplate({ name: user.name, url });
      try {
        await sendMail({ to: user.email, subject: t.subject, text: t.text, html: t.html });
      } catch (err) {
        log.error('failed to send verification email', { err: errString(err) });
      }
    },
  },
  // Shorten the session window from the 7-day default. A stolen cookie
  // now stops working after a day of inactivity instead of a week, and
  // `updateAge: 1h` slides the expiry forward on active use so legit
  // users don't get bounced mid-session.
  session: {
    expiresIn: 60 * 60 * 24, // 24 hours
    updateAge: 60 * 60, // re-issue at most once per hour
  },
  user: {
    // Self-serve account deletion. better-auth tears down the user row
    // (plus cascaded sessions / accounts) when the client calls
    // authClient.deleteUser(). Mods owned by the deleted user keep
    // existing rows because mod.ownerId is `set null` on user delete
    // (see packages/db schema) — they just become unowned and stop
    // accepting edits.
    deleteUser: {
      enabled: true,
    },
    // Self-serve email change. When the current email is verified,
    // better-auth sends an approval link to the CURRENT address (not the
    // new one) so a hijacked session can't silently move the account to
    // an attacker's inbox. The email only flips after that link is
    // clicked. In dev without SMTP the link is logged to stdout.
    changeEmail: {
      enabled: true,
      sendChangeEmailVerification: async ({ user, newEmail, url }) => {
        const t = changeEmailTemplate({ name: user.name, newEmail, url });
        try {
          await sendMail({ to: user.email, subject: t.subject, text: t.text, html: t.html });
        } catch (err) {
          log.error('failed to send change-email verification', { err: errString(err) });
        }
      },
    },
  },
  // Desktop-relay OAuth callbacks must not depend on the browser `state`
  // cookie. /desktop-auth/start is a textbook "stateful bounce" (land →
  // Set-Cookie → instant 302 to the provider), and privacy browsers (Brave
  // bounce-tracking mitigation, and friends) put cookies set during such a
  // bounce in ephemeral storage or drop them — verified live: the callback
  // arrived carrying the long-lived session cookie but NOT the state cookie
  // that /start had set 2 seconds earlier, with BOTH SameSite=Lax and
  // SameSite=None. So for callbacks whose state row targets the desktop relay
  // we skip the cookie half of the state check (better-auth's own oauth-proxy
  // plugin uses this exact escape hatch). The DB half still fully applies:
  // the state param must match an unguessable, single-use verification row
  // that expires in 10 minutes. Web OAuth keeps the cookie binding — the flag
  // is explicitly reset on every non-relay callback so it can never stick.
  // The relay's initiator binding is re-established end-to-end by the app
  // nonce (`app` param) relayed through /desktop-auth/start → callbackURL →
  // deep link, which the desktop app verifies before accepting the token.
  hooks: {
    before: createAuthMiddleware(async (ctx) => {
      if (ctx.path !== '/callback/:id') return;
      let skip = false;
      const state = ctx.query?.state ?? ctx.body?.state;
      if (typeof state === 'string' && state) {
        const row = await ctx.context.internalAdapter
          .findVerificationValue(state)
          .catch(() => null);
        if (row) {
          try {
            const parsed = JSON.parse(row.value) as { callbackURL?: unknown };
            skip =
              typeof parsed.callbackURL === 'string' &&
              parsed.callbackURL.startsWith('/api/desktop-auth/complete');
          } catch {
            // not a JSON state row → not ours; keep the cookie check.
          }
        }
      }
      ctx.context.oauthConfig.skipStateCookieCheck = skip;
    }),
  },
  advanced: {
    useSecureCookies: isProduction,
    disableCSRFCheck: false,
    // Production Tauri builds (all OSes) call the HTTPS API from a different
    // site (tauri://localhost, https://tauri.localhost, etc.) and need
    // SameSite=None. Dev uses the Vite proxy (same-origin) — Lax is fine there.
    // Applying None+Secure in dev breaks local `http://localhost:3001` sign-in.
    ...(isProduction
      ? {
          defaultCookieAttributes: {
            sameSite: 'none' as const,
            secure: true,
          },
        }
      : {}),
  },
});

export type Session = typeof auth.$Infer.Session;
