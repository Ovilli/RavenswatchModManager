import { describe, expect, it } from 'vitest';

process.env.DATABASE_URL ??= 'postgres://user:pass@localhost:5432/db';
process.env.BETTER_AUTH_SECRET ??= 'x'.repeat(32);

const { withVerifyCallback } = await import('../src/mailer.js');

describe('withVerifyCallback', () => {
  it('sends a sign-up verification link (no callbackURL) to the website', () => {
    const out = new URL(
      withVerifyCallback(
        'https://api.rsmm.me/api/auth/verify-email?token=abc',
        'https://rsmm.me/account',
      ),
    );
    expect(out.searchParams.get('token')).toBe('abc');
    expect(out.searchParams.get('callbackURL')).toBe('https://rsmm.me/account');
  });

  it('keeps a callbackURL the caller chose', () => {
    const url =
      'https://api.rsmm.me/api/auth/verify-email?token=abc&callbackURL=https%3A%2F%2Frsmm.me%2Fx';
    expect(
      new URL(withVerifyCallback(url, 'https://rsmm.me/account')).searchParams.get('callbackURL'),
    ).toBe('https://rsmm.me/x');
  });
});
