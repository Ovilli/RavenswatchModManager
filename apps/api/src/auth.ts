import { getDb, schema } from '@rsmm/db';
import { betterAuth } from 'better-auth';
import { drizzleAdapter } from 'better-auth/adapters/drizzle';
import { env, githubConfigured, googleConfigured, smtpConfigured } from './env';
import { resetPasswordTemplate, sendMail, verifyEmailTemplate } from './mailer';

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
    autoSignIn: true,
    // Verification requires SMTP. When SMTP is unconfigured we log the
    // link to stdout and skip the gate — local dev keeps working
    // without provisioning a mail server.
    requireEmailVerification: smtpConfigured(),
    sendResetPassword: async ({ user, url }) => {
      const t = resetPasswordTemplate({ name: user.name, url });
      await sendMail({ to: user.email, subject: t.subject, text: t.text, html: t.html });
    },
  },
  emailVerification: {
    sendOnSignUp: true,
    autoSignInAfterVerification: true,
    sendVerificationEmail: async ({ user, url }) => {
      const t = verifyEmailTemplate({ name: user.name, url });
      await sendMail({ to: user.email, subject: t.subject, text: t.text, html: t.html });
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
  advanced: {
    useSecureCookies: process.env.NODE_ENV === 'production',
    disableCSRFCheck: false,
  },
});

export type Session = typeof auth.$Infer.Session;
