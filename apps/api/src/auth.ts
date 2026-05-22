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
    requireEmailVerification: false,
  },
  advanced: {
    useSecureCookies: process.env.NODE_ENV === 'production',
    disableCSRFCheck: false,
  },
});

export type Session = typeof auth.$Infer.Session;
