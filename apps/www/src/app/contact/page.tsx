import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@rsmm/ui';
import type { Metadata } from 'next';
import Link from 'next/link';

export const metadata: Metadata = {
  title: 'Contact · Ravenswatch Mod Manager',
  description:
    'How to reach the Ravenswatch Mod Manager team — report a bug, ask a question, request mod removal, or contribute.',
  alternates: { canonical: '/contact' },
};

const REPO = 'https://github.com/Ovilli/RavenswatchModManager';

export default function ContactPage() {
  return (
    <main className="container mx-auto px-6 py-16 animate-page-in">
      <Card className="mx-auto max-w-3xl grimoire-card">
        <CardHeader>
          <CardTitle>Contact</CardTitle>
          <CardDescription>Questions, bug reports, takedowns, and contributions.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-6 text-sm leading-relaxed text-muted-foreground">
          <section className="space-y-2">
            <h2 className="text-lg font-semibold text-foreground">General &amp; support</h2>
            <p>
              The fastest way to reach the maintainers is through the project&apos;s GitHub
              repository. Open an issue for bugs and feature requests, or start a discussion for
              questions:
            </p>
            <ul className="list-disc space-y-1 pl-5">
              <li>
                Issues &amp; bug reports:{' '}
                <a
                  href={`${REPO}/issues`}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="underline hover:text-foreground"
                >
                  {REPO.replace('https://', '')}/issues
                </a>
              </li>
              <li>
                Source &amp; documentation:{' '}
                <a
                  href={REPO}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="underline hover:text-foreground"
                >
                  {REPO.replace('https://', '')}
                </a>
              </li>
            </ul>
          </section>

          <section className="space-y-2">
            <h2 className="text-lg font-semibold text-foreground">Email</h2>
            <p>
              For matters that are not suited to a public issue — account problems, privacy
              requests, or content takedowns — email{' '}
              <a href="mailto:contact@rsmm.me" className="underline hover:text-foreground">
                contact@rsmm.me
              </a>
              .
            </p>
          </section>

          <section className="space-y-2">
            <h2 className="text-lg font-semibold text-foreground">
              Report a mod or request removal
            </h2>
            <p>
              The fastest way to flag a mod is the <strong>Report</strong> button on its page — it
              files the report directly into the moderation queue, where a moderator reviews it. Use
              it for malware, stolen work, broken uploads, spam, or inappropriate content.
            </p>
            <p>
              For copyright takedowns and other matters best handled privately, email the address
              above with a link to the mod and a description of the issue, or see the{' '}
              <Link href="/dmca" className="underline hover:text-foreground">
                Content Policy
              </Link>
              .
            </p>
          </section>

          <section className="space-y-2">
            <h2 className="text-lg font-semibold text-foreground">Privacy &amp; data requests</h2>
            <p>
              To access, export, or delete your personal data, see the{' '}
              <Link href="/privacy" className="underline hover:text-foreground">
                Privacy Policy
              </Link>{' '}
              or email the contact address. You can also delete your account directly from your{' '}
              <Link href="/account" className="underline hover:text-foreground">
                account settings
              </Link>
              .
            </p>
          </section>
        </CardContent>
      </Card>
    </main>
  );
}
