import { getDb, schema } from '@rsmm/db';
import { betterAuth } from 'better-auth';
import { drizzleAdapter } from 'better-auth/adapters/drizzle';
import { env } from './env';

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
  emailAndPassword: {
    enabled: true,
    autoSignIn: true,
    // `requireEmailVerification` stays false until an SMTP/transactional
    // email sender is wired up via Better Auth's emailVerification hook.
    // Flipping it on without that breaks every signup (Better Auth has
    // nothing to call to send the verification mail).
    requireEmailVerification: false,
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
