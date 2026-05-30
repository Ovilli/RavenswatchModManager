import nodemailer, { type Transporter } from 'nodemailer';
import { env, isProduction, smtpConfigured } from './env.js';

let cached: Transporter | null = null;

function getTransport(): Transporter {
  if (cached) return cached;
  if (!smtpConfigured()) {
    throw new Error(
      'SMTP not configured. Set SMTP_HOST, SMTP_USER, SMTP_PASS (and optionally SMTP_PORT, SMTP_SECURE, EMAIL_FROM).',
    );
  }
  cached = nodemailer.createTransport({
    host: env.smtp.host,
    port: env.smtp.port,
    secure: env.smtp.secure,
    auth: { user: env.smtp.user, pass: env.smtp.pass },
  });
  return cached;
}

export interface MailMessage {
  to: string;
  subject: string;
  text: string;
  html?: string;
}

export async function sendMail(msg: MailMessage): Promise<void> {
  if (!smtpConfigured()) {
    if (isProduction) {
      throw new Error('SMTP is not configured; refusing to continue without email delivery.');
    }
    // In dev we log instead of failing so the signup flow keeps working
    // even when an operator hasn't wired SMTP yet. The verification URL
    // is on stdout — copy-paste it into the browser to verify.
    console.log(
      `[mailer] SMTP not configured — would send:\n  to:      ${msg.to}\n  subject: ${msg.subject}\n  body:    ${msg.text}`,
    );
    return;
  }
  await getTransport().sendMail({
    from: env.smtp.from,
    to: msg.to,
    subject: msg.subject,
    text: msg.text,
    html: msg.html,
  });
}

function htmlEscape(s: string): string {
  return s
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

export function verifyEmailTemplate(args: { name: string; url: string }): {
  subject: string;
  text: string;
  html: string;
} {
  const safeName = htmlEscape(args.name || 'modder');
  const safeUrl = htmlEscape(args.url);
  const subject = 'Verify your Ravenswatch Mod Manager account';
  const text = `Hi ${safeName},\n\nConfirm your email to finish creating your account:\n${args.url}\n\nIf you didn't request this, you can ignore this message.`;
  const html = `
<!doctype html>
<html lang="en">
  <body style="font-family: -apple-system, system-ui, sans-serif; max-width: 540px; margin: 0 auto; padding: 24px; color: #1f1f1f;">
    <h2 style="margin: 0 0 12px;">Verify your email</h2>
    <p>Hi ${safeName},</p>
    <p>Confirm your email to finish creating your Ravenswatch Mod Manager account.</p>
    <p>
      <a href="${safeUrl}" style="display: inline-block; padding: 10px 18px; background: #7d1a1a; color: #fff; text-decoration: none; border-radius: 6px;">
        Confirm email
      </a>
    </p>
    <p style="font-size: 13px; color: #555;">Or paste this URL into your browser: <br /><code>${safeUrl}</code></p>
    <p style="font-size: 12px; color: #888;">If you didn't request this, you can ignore this email.</p>
  </body>
</html>`.trim();
  return { subject, text, html };
}

export function changeEmailTemplate(args: { name: string; newEmail: string; url: string }): {
  subject: string;
  text: string;
  html: string;
} {
  const safeName = htmlEscape(args.name || 'modder');
  const safeUrl = htmlEscape(args.url);
  const safeNew = htmlEscape(args.newEmail);
  const subject = 'Confirm your new Ravenswatch Mod Manager email';
  const text = `Hi ${safeName},\n\nWe received a request to change the email on your account to ${args.newEmail}.\nApprove the change using this link:\n${args.url}\n\nIf you didn't request this, ignore this message and your email stays unchanged.`;
  const html = `
<!doctype html>
<html lang="en">
  <body style="font-family: -apple-system, system-ui, sans-serif; max-width: 540px; margin: 0 auto; padding: 24px; color: #1f1f1f;">
    <h2 style="margin: 0 0 12px;">Confirm your new email</h2>
    <p>Hi ${safeName},</p>
    <p>We received a request to change the email on your account to <strong>${safeNew}</strong>. Click below to approve it.</p>
    <p>
      <a href="${safeUrl}" style="display: inline-block; padding: 10px 18px; background: #7d1a1a; color: #fff; text-decoration: none; border-radius: 6px;">
        Confirm email change
      </a>
    </p>
    <p style="font-size: 13px; color: #555;">Or paste this URL: <br /><code>${safeUrl}</code></p>
    <p style="font-size: 12px; color: #888;">If you didn't request this, ignore this email and your address stays unchanged.</p>
  </body>
</html>`.trim();
  return { subject, text, html };
}

export function resetPasswordTemplate(args: { name: string; url: string }): {
  subject: string;
  text: string;
  html: string;
} {
  const safeName = htmlEscape(args.name || 'modder');
  const safeUrl = htmlEscape(args.url);
  const subject = 'Reset your Ravenswatch Mod Manager password';
  const text = `Hi ${safeName},\n\nReset your password using this link:\n${args.url}\n\nThe link expires in one hour. If you didn't request this, you can ignore this message.`;
  const html = `
<!doctype html>
<html lang="en">
  <body style="font-family: -apple-system, system-ui, sans-serif; max-width: 540px; margin: 0 auto; padding: 24px; color: #1f1f1f;">
    <h2 style="margin: 0 0 12px;">Reset your password</h2>
    <p>Hi ${safeName},</p>
    <p>Click the button below to set a new password. The link expires in one hour.</p>
    <p>
      <a href="${safeUrl}" style="display: inline-block; padding: 10px 18px; background: #7d1a1a; color: #fff; text-decoration: none; border-radius: 6px;">
        Reset password
      </a>
    </p>
    <p style="font-size: 13px; color: #555;">Or paste this URL: <br /><code>${safeUrl}</code></p>
    <p style="font-size: 12px; color: #888;">If you didn't request this, ignore this email.</p>
  </body>
</html>`.trim();
  return { subject, text, html };
}
