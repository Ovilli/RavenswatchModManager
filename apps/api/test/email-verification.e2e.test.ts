import { getDb, schema } from '@rsmm/db';
import { eq } from 'drizzle-orm';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import { app } from '../src/app.js';
import { env, smtpConfigured, testmailConfigured } from '../src/env.js';

// End-to-end coverage of the signup → verification-email → verify flow.
//
// What it exercises: a real signup hits Better Auth, which sends a real
// verification email through SMTP (IONOS) to a testmail.app inbox. The test
// then polls the testmail JSON API for that mail, pulls the verify link out
// of it, and replays the link back through the Hono app — proving the link
// the user actually receives marks the account verified.
//
// Requirements (otherwise the suite self-skips, so CI without secrets is green):
//   SMTP_HOST/SMTP_USER/SMTP_PASS  — the API must be able to SEND
//   TESTMAIL_APIKEY/TESTMAIL_NAMESPACE — the inbox that RECEIVES
//   DATABASE_URL pointing at a reachable Postgres (pnpm db:up)

const ready = smtpConfigured() && testmailConfigured();
const suite = ready ? describe : describe.skip;

const TESTMAIL_JSON = 'https://api.testmail.app/api/json';

interface TestmailEmail {
  subject: string;
  from: string;
  text: string;
  html: string;
}
interface TestmailResult {
  result: 'success' | 'fail';
  message: string | null;
  count: number;
  emails: TestmailEmail[];
}

// Poll the testmail inbox for a mail with the given tag received after
// `since`. Returns on the first match. We poll manually (rather than the
// server-side `livequery`) so the deadline is fully ours and the loop can't
// outlive the vitest timeout via 307 redirect chains.
async function waitForEmail(args: {
  tag: string;
  since: number;
  deadlineMs?: number;
}): Promise<TestmailEmail> {
  const deadline = Date.now() + (args.deadlineMs ?? 4 * 60 * 1000);
  const url = new URL(TESTMAIL_JSON);
  url.searchParams.set('apikey', env.testmail.apikey);
  url.searchParams.set('namespace', env.testmail.namespace);
  url.searchParams.set('tag', args.tag);
  url.searchParams.set('timestamp_from', String(args.since));
  url.searchParams.set('limit', '1');

  while (Date.now() < deadline) {
    const res = await fetch(url, { headers: { accept: 'application/json' } });
    if (res.status === 429) {
      // Rate limited — back off harder.
      await sleep(5000);
      continue;
    }
    const body = (await res.json()) as TestmailResult;
    if (body.result === 'fail') throw new Error(`testmail error: ${body.message}`);
    if (body.count > 0 && body.emails[0]) return body.emails[0];
    await sleep(3000);
  }
  throw new Error(`no email for tag "${args.tag}" within deadline`);
}

function sleep(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms));
}

// The verify link Better Auth embeds points at
// <BETTER_AUTH_URL>/api/auth/verify-email?token=...&callbackURL=...
// Pull it from whichever body part carries it.
function extractVerifyUrl(email: TestmailEmail): string {
  const haystack = `${email.text}\n${email.html}`;
  const m = haystack.match(/https?:\/\/[^\s"'<>]*\/api\/auth\/verify-email\?[^\s"'<>]+/);
  if (!m) throw new Error('verify-email URL not found in email body');
  // HTML-escaped &amp; sneaks into the html part — normalize it.
  return m[0].replace(/&amp;/g, '&');
}

suite('email verification e2e', () => {
  // Unique tag per run so parallel/CI runs never collide; doubles as a
  // randomized local-part. nanosecond-ish suffix keeps it collision-free.
  const tag = `verify-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
  const email = `${env.testmail.namespace}.${tag}@inbox.testmail.app`;
  const password = 'Sup3rSecret!pw';
  const startTs = Date.now();

  afterAll(async () => {
    // Tear down the user row so the run is idempotent. Cascades drop the
    // session/account/verification rows too.
    try {
      await getDb().delete(schema.users).where(eq(schema.users.email, email));
    } catch {
      /* best-effort cleanup */
    }
  });

  it('signs up, receives the email, and verifies via the link', async () => {
    // 1. Sign up through the real auth handler.
    const signup = await app.fetch(
      new Request('http://local.test/api/auth/sign-up/email', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ name: 'E2E Tester', email, password }),
      }),
    );
    expect([200, 201]).toContain(signup.status);

    // 2. Account starts unverified.
    const before = await getDb()
      .select()
      .from(schema.users)
      .where(eq(schema.users.email, email));
    expect(before).toHaveLength(1);
    expect(before[0]?.emailVerified).toBe(false);

    // 3. Wait for the verification email to hit the testmail inbox.
    const mail = await waitForEmail({ tag, since: startTs });
    expect(mail.subject).toBe('Verify your Ravenswatch Mod Manager account');

    // 4. Replay the embedded verify link through the app.
    const verifyUrl = extractVerifyUrl(mail);
    const verify = await app.fetch(new Request(verifyUrl, { redirect: 'manual' }));
    // Better Auth redirects to callbackURL on success.
    expect([200, 302]).toContain(verify.status);

    // 5. The account is now verified.
    const after = await getDb()
      .select()
      .from(schema.users)
      .where(eq(schema.users.email, email));
    expect(after[0]?.emailVerified).toBe(true);
  });
});
