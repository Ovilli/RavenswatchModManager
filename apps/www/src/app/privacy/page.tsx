import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@rsmm/ui';
import Link from 'next/link';

export default function PrivacyPage() {
  return (
    <main className="container mx-auto px-6 py-16 animate-page-in">
      <Card className="mx-auto max-w-3xl grimoire-card">
        <CardHeader>
          <CardTitle>Privacy Policy</CardTitle>
          <CardDescription>How your data is collected, stored, and processed.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-6 text-sm text-muted-foreground">
          <section className="space-y-2">
            <h2 className="text-lg font-semibold text-foreground">1. Data Controller</h2>
            <p>
              The Ravenswatch Mod Manager project is an open-source community project. Contact
              details are available in the project repository. This privacy policy applies to the
              registry website and the API backend.
            </p>
          </section>

          <section className="space-y-2">
            <h2 className="text-lg font-semibold text-foreground">2. Data We Collect</h2>
            <p>When you create an account or use the registry, we may collect:</p>
            <ul className="list-disc space-y-1 pl-5">
              <li>Email address — for account authentication and communication</li>
              <li>Display name — shown publicly alongside your mod submissions</li>
              <li>Mod metadata — uploaded mod files, descriptions, and version history</li>
              <li>Usage telemetry — anonymized download counts and mod popularity metrics</li>
            </ul>
          </section>

          <section className="space-y-2">
            <h2 className="text-lg font-semibold text-foreground">3. How We Store Data</h2>
            <p>
              Account data is stored in a PostgreSQL database hosted on Neon. Mod files are
              uploaded to S3-compatible object storage. All connections are encrypted via TLS.
            </p>
          </section>

          <section className="space-y-2">
            <h2 className="text-lg font-semibold text-foreground">4. Third-Party Services</h2>
            <ul className="list-disc space-y-1 pl-5">
              <li>Neon — PostgreSQL database hosting (EU or US region)</li>
              <li>S3-compatible storage — mod file hosting</li>
              <li>GitHub — authentication provider (optional)</li>
              <li>Vercel — web application hosting</li>
            </ul>
          </section>

          <section className="space-y-2">
            <h2 className="text-lg font-semibold text-foreground">5. Data Retention</h2>
            <p>
              Account data is retained until you request deletion. Mod files remain available
              until removed by the author or moderators. Telemetry data is aggregated and
              anonymized after 12 months.
            </p>
          </section>

          <section className="space-y-2">
            <h2 className="text-lg font-semibold text-foreground">6. Your Rights (GDPR)</h2>
            <p>You have the right to:</p>
            <ul className="list-disc space-y-1 pl-5">
              <li>Access your personal data</li>
              <li>Rectify inaccurate data</li>
              <li>Delete your account and associated data</li>
              <li>Object to processing of your data</li>
              <li>Export your data in a machine-readable format</li>
            </ul>
            <p className="mt-2">
              To exercise these rights, open an issue on the project repository or contact the
              maintainers through the channels listed on GitHub.
            </p>
          </section>

          <section className="space-y-2">
            <h2 className="text-lg font-semibold text-foreground">7. Changes to This Policy</h2>
            <p>
              This privacy policy may be updated from time to time. Changes will be announced via
              the project repository.
            </p>
          </section>
        </CardContent>
      </Card>

      <p className="mt-8 text-center text-xs text-muted-foreground">
        <Link href="/" className="underline hover:text-foreground">Home</Link>
        {' · '}
        <Link href="/legal" className="underline hover:text-foreground">Legal Notice</Link>
      </p>
    </main>
  );
}
