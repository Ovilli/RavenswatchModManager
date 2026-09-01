import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@rsmm/ui';
import type { Metadata } from 'next';
import Link from 'next/link';

export const metadata: Metadata = {
  title: 'Privacy Policy · Ravenswatch Mod Manager',
  description:
    'What data the Ravenswatch Mod Manager collects, how anonymous usage and crash reporting works, and how to turn it off.',
  alternates: { canonical: '/privacy' },
};

// Bump whenever a section changes materially. Shown at the top so a returning
// reader can tell at a glance whether anything moved since they last agreed.
const LAST_UPDATED = '24 August 2026';

function Section({ n, title, children }: { n: number; title: string; children: React.ReactNode }) {
  return (
    <section className="space-y-2">
      <h2 className="text-lg font-semibold text-foreground">
        {n}. {title}
      </h2>
      {children}
    </section>
  );
}

export default function PrivacyPage() {
  return (
    <main className="container mx-auto px-6 py-16 animate-page-in">
      <Card className="mx-auto max-w-3xl grimoire-card">
        <CardHeader>
          <CardTitle>Privacy Policy</CardTitle>
          <CardDescription>
            How your data is collected, stored, and processed. Last updated {LAST_UPDATED}.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-6 text-sm text-muted-foreground">
          <p className="rounded-md border border-border/70 bg-background/50 p-3">
            <strong className="text-foreground">The short version.</strong> An account needs an
            email address and a display name. Usage and crash reports from the desktop app are{' '}
            <strong className="text-foreground">anonymous by default</strong> and you can turn them
            off entirely. Nothing you do in the manager — which mods you install, your game files,
            your save data — is uploaded. Change any of it in{' '}
            <Link href="/account" className="underline underline-offset-2 hover:text-foreground">
              Account → Privacy &amp; data sharing
            </Link>
            .
          </p>

          <Section n={1} title="Data Controller">
            <p>
              The Ravenswatch Mod Manager project is an open-source community project. Contact
              details are in the{' '}
              <Link href="/legal" className="underline underline-offset-2 hover:text-foreground">
                legal notice
              </Link>{' '}
              and in the project repository. This policy covers the registry website (rsmm.me), the
              API backend (api.rsmm.me), and the desktop client.
            </p>
          </Section>

          <Section n={2} title="Data We Collect">
            <p>
              <strong className="text-foreground">Account data</strong>, when you register:
            </p>
            <ul className="list-disc space-y-1 pl-5">
              <li>Email address — authentication, password reset, and service notices</li>
              <li>Display name and optional handle — shown publicly beside your submissions</li>
              <li>Avatar image, if you upload one</li>
              <li>
                Password hash, or the identifier issued by your sign-in provider if you use one
              </li>
            </ul>
            <p className="pt-2">
              <strong className="text-foreground">Session data</strong>, while you are signed in: a
              session token, its expiry, and the IP address and browser user-agent the session was
              created from. These are security records — they let us end a stolen session — and are
              deleted when the session expires or you sign out.
            </p>
            <p className="pt-2">
              <strong className="text-foreground">Content you publish</strong>: mod files and their
              metadata, descriptions, version history, screenshots, collections, guides, reviews and
              ratings. This is public by design.
            </p>
            <p className="pt-2">
              <strong className="text-foreground">Download counts</strong>: a per-mod, per-day
              counter. It records that a download happened, not who made it.
            </p>
            <p className="pt-2">
              <strong className="text-foreground">Optional reports from the desktop app</strong> —
              see section 3.
            </p>
            <p className="pt-2">
              We do <strong className="text-foreground">not</strong> collect the list of mods you
              have installed, your game directory contents, your save files, or any in-game
              activity. The manager works on your machine and does not report what it finds there.
            </p>
          </Section>

          <Section n={3} title="Usage and Crash Reports, and Your Choice">
            <p>
              The desktop client can send two kinds of report. Each is controlled separately in{' '}
              <Link href="/account" className="underline underline-offset-2 hover:text-foreground">
                Account → Privacy &amp; data sharing
              </Link>
              , with three settings: <em>don’t send</em>, <em>send anonymously</em> (the default),
              or <em>send linked to my account</em>.
            </p>
            <ul className="list-disc space-y-1 pl-5">
              <li>
                <strong className="text-foreground">Usage reports</strong> — one record when the
                manager applies mods: the RSMM version, your operating system family
                (Windows/Linux), the detected game build, whether the operation succeeded, and how
                long it took.
              </li>
              <li>
                <strong className="text-foreground">Crash reports</strong> — the error type, message
                and stack trace when the app hits an unhandled error. A stack trace can incidentally
                contain file paths from your machine, which is why this is a separate choice from
                usage reporting.
              </li>
            </ul>
            <p className="pt-2">
              <strong className="text-foreground">What each setting means.</strong>{' '}
              <em>Don’t send</em> — the server discards the submission; no row is written.{' '}
              <em>Send anonymously</em> — the record is stored with no account identifier, so it
              counts toward aggregate figures (how many installs succeeded, which versions are in
              use) but cannot be traced back to you. <em>Send linked</em> — your account id stays
              attached so a maintainer can follow up with you about a specific crash.
            </p>
            <p className="pt-2">
              The choice is enforced on the server, not just in the app. It therefore applies to
              every device you are signed in on, including one running an older build. Reports sent
              by a client that is not signed in have no account to attach and are always anonymous.
            </p>
            <p className="pt-2">
              The desktop app also has its own local switch for crash uploads. Either switch being
              off is enough to stop the upload. Local log entries are written on your machine
              regardless — they never leave it, and they are what a bug report needs.
            </p>
            <p className="pt-2">
              <strong className="text-foreground">Shared logs are different.</strong> When you press{' '}
              <em>Share link</em> on the app’s Log screen, the app uploads the log text you were
              shown in the preview and gives you a URL to paste into a bug report. This is not
              covered by the settings above, because nothing is sent until you ask for it — the act
              of sharing is the consent. The page is <em>unlisted, not private</em>: anyone you give
              the link to can read it, and you should treat it as public. It is deleted
              automatically 30 days after upload.
            </p>
            <p className="pt-2">
              Before uploading, the app replaces your account name in file paths, e-mail addresses,
              IP addresses, Steam IDs and player names with placeholders. That is pattern matching
              on a log we do not control, so it is a strong default rather than a guarantee — the
              dialog shows you the exact text first, and you can turn the replacement off. Read the
              preview before you share.
            </p>
          </Section>

          <Section n={4} title="What Other People Can See">
            <p>Two further choices control your visibility to other users:</p>
            <ul className="list-disc space-y-1 pl-5">
              <li>
                <strong className="text-foreground">Public author profile</strong> — on by default.
                Turning it off makes your profile page return “not found” for visitors. Your
                published mods stay in the registry, credited to the author name written on each
                one.
              </li>
              <li>
                <strong className="text-foreground">Public download counts</strong> — on by default.
                Turning it off hides the per-mod download number from the public listing and detail
                pages. You still see your own figures, and site-wide totals still include them.
              </li>
            </ul>
          </Section>

          <Section n={5} title="Email">
            <p>
              <strong className="text-foreground">Transactional email</strong> — sign-in and
              password-reset messages, and notices about your own content (a mod approved, taken
              down, or reported). These are part of running the account and are sent whatever your
              settings say.
            </p>
            <p className="pt-2">
              <strong className="text-foreground">Announcements</strong> — occasional email about
              new releases. <strong className="text-foreground">Off unless you turn it on</strong>,
              and revocable at any time in Account → Privacy.
            </p>
          </Section>

          <Section n={6} title="How We Store Data">
            <p>
              Account, mod and report data is stored in a PostgreSQL database hosted on Neon. Mod
              files, screenshots and avatars are stored in S3-compatible object storage. All
              connections are encrypted with TLS.
            </p>
          </Section>

          <Section n={7} title="Third-Party Services">
            <ul className="list-disc space-y-1 pl-5">
              <li>Neon — PostgreSQL database hosting</li>
              <li>Cloudflare R2 / S3-compatible storage — mod files, images and avatars</li>
              <li>Vercel — hosting for the website and the API</li>
              <li>GitHub and Google — optional sign-in providers, and release file downloads</li>
              <li>
                VirusTotal — every uploaded mod file is submitted for malware scanning before it
                becomes downloadable. Files submitted to VirusTotal are shared with its security
                partners; do not upload anything you would not want scanned.
              </li>
              <li>An SMTP provider — delivery of the email described in section 5</li>
              <li>Google AdSense — advertising on this website only (section 9)</li>
            </ul>
            <p className="pt-2">
              The desktop application carries no advertising and no third-party analytics.
            </p>
          </Section>

          <Section n={8} title="Legal Basis and Retention">
            <p>
              Account and content data is processed to perform the service you asked for (Art.
              6(1)(b) GDPR). Session records and malware scanning rest on our legitimate interest in
              keeping the registry secure (Art. 6(1)(f)). Usage and crash reports, and announcement
              email, rest on your consent (Art. 6(1)(a)), which you can withdraw at any time in
              Account → Privacy without affecting anything processed before you did.
            </p>
            <p className="pt-2">
              Account data is kept until you delete your account. Mod files stay available until
              removed by their author or by a moderator. Session records expire with the session.
              Usage and crash reports are kept for 12 months and then deleted. Logs you share by
              link are deleted 30 days after upload. Download counters are day-buckets with no
              identifier and are kept indefinitely.
            </p>
          </Section>

          <Section n={9} title="Advertising &amp; Cookies">
            <p>
              This website uses cookies and may display advertising served by Google AdSense and its
              partners. Third-party vendors, including Google, use cookies to serve ads based on
              your prior visits to this and other websites.
            </p>
            <ul className="list-disc space-y-1 pl-5">
              <li>
                Google&apos;s use of advertising cookies (including the DoubleClick DART cookie)
                enables it and its partners to serve ads to you based on your visit to this site
                and/or other sites on the Internet.
              </li>
              <li>
                You may opt out of personalised advertising by visiting{' '}
                <a
                  href="https://www.google.com/settings/ads"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="underline hover:text-foreground"
                >
                  Google Ads Settings
                </a>
                .
              </li>
              <li>
                You can opt out of a third-party vendor&apos;s use of cookies for personalised
                advertising at{' '}
                <a
                  href="https://www.aboutads.info/choices/"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="underline hover:text-foreground"
                >
                  aboutads.info/choices
                </a>
                .
              </li>
              <li>
                Visitors in the EU/EEA/UK and other applicable regions are shown a consent prompt,
                managed through a Google-certified Consent Management Platform, before personalised
                ads and non-essential cookies are used. Your choice is recorded and applied via
                Google Consent Mode, and you can withdraw or change it at any time by clearing this
                site&apos;s cookies in your browser.
              </li>
            </ul>
            <p>
              Essential cookies required for sign-in and security are always set; you can disable
              all cookies in your browser settings, though parts of the site may stop working. The
              advertising described here applies to this website only — the desktop application
              shows no ads and sets no advertising cookies.
            </p>
          </Section>

          <Section n={10} title="Your Rights (GDPR)">
            <p>You have the right to:</p>
            <ul className="list-disc space-y-1 pl-5">
              <li>Access your personal data</li>
              <li>Rectify inaccurate data</li>
              <li>Delete your account and associated data</li>
              <li>Restrict or object to processing of your data</li>
              <li>Withdraw consent for anything based on it, at any time</li>
              <li>Export your data in a machine-readable format</li>
              <li>Lodge a complaint with your national data protection authority</li>
            </ul>
            <p className="pt-2">
              The reporting and visibility choices in{' '}
              <Link href="/account" className="underline underline-offset-2 hover:text-foreground">
                Account → Privacy &amp; data sharing
              </Link>{' '}
              exercise several of these directly. For the rest, open an issue on the project
              repository or contact the maintainers through the channels listed on GitHub.
            </p>
            <p className="pt-2">
              Reports you chose to send anonymously carry no identifier, so they cannot be located
              or deleted on request — that is the trade-off that makes them anonymous. Choose{' '}
              <em>don’t send</em> if you would rather they never existed.
            </p>
          </Section>

          <Section n={11} title="Children">
            <p>
              This service is not directed at children under 16. We do not knowingly collect data
              from them; if you believe a child has created an account, contact the maintainers and
              it will be removed.
            </p>
          </Section>

          <Section n={12} title="Changes to This Policy">
            <p>
              This privacy policy may be updated from time to time. The date at the top of this page
              records the last change, and material changes are announced through the project
              repository.
            </p>
          </Section>
        </CardContent>
      </Card>

      <p className="mt-8 text-center text-xs text-muted-foreground">
        <Link href="/" className="underline hover:text-foreground">
          Home
        </Link>
        {' · '}
        <Link href="/legal" className="underline hover:text-foreground">
          Legal Notice
        </Link>
        {' · '}
        <Link href="/account" className="underline hover:text-foreground">
          Your privacy settings
        </Link>
      </p>
    </main>
  );
}
