import { getDb, schema } from '@rsmm/db';
import { betterAuth } from 'better-auth';
import { drizzleAdapter } from 'better-auth/adapters/drizzle';
import { env, githubConfigured, googleConfigured, isProduction, smtpConfigured } from './env.js';
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
        console.error('Failed to send password-reset email:', err);
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
        console.error('Failed to send verification email:', err);
      }
    },
  },
  // Shorten the session window from the 7-day default. A stolen cookie
  // now stops working after a day of inactivity instead of a week, and
  // `updateAge: 1h` slides the expiry forward on active use so legit
  // users don't get bounced mid-session.
  session: {
    expiresIn: 60 * 60 * 24,        // 24 hours
    updateAge: 60 * 60,             // re-issue at most once per hour
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
          console.error('Failed to send change-email verification:', err);
        }
      },
    },
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
