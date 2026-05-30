import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@rsmm/ui';
import Link from 'next/link';

export default function LegalPage() {
  return (
    <main className="container mx-auto px-6 py-16 animate-page-in">
      <Card className="mx-auto max-w-3xl grimoire-card">
        <CardHeader>
          <CardTitle>Legal Notice</CardTitle>
          <CardDescription>
            Impressum — required disclosure under German law (§5 TMG).
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-6 text-sm text-muted-foreground">
          <section className="space-y-2">
            <h2 className="text-lg font-semibold text-foreground">Contact</h2>
            <p>
              Ravenswatch Mod Manager is an open-source project maintained by contributors. This is
              an unofficial third-party tool and is not affiliated with or endorsed by Passtech
              Games or NACON.
            </p>
            <p>
              Project repository:{' '}
              <a
                href="https://github.com/Ovilli/RavenswatchModManager"
                target="_blank"
                rel="noopener noreferrer"
                className="underline hover:text-foreground"
              >
                github.com/Ovilli/RavenswatchModManager
              </a>
            </p>
          </section>

          <section className="space-y-2">
            <h2 className="text-lg font-semibold text-foreground">Disclaimer</h2>
            <p>
              This software is provided &quot;as is&quot;, without warranty of any kind, express or
              implied. The mod manager modifies game files locally; users are responsible for
              backing up their game data. The project maintainers assume no liability for damages or
              data loss arising from the use of this software.
            </p>
          </section>

          <section className="space-y-2">
            <h2 className="text-lg font-semibold text-foreground">License</h2>
            <p>
              The source code is distributed under the terms of the license found in the repository.
              Third-party components bundled with the desktop client are listed in the{' '}
              <a
                href="https://github.com/Ovilli/RavenswatchModManager/blob/main/THIRD_PARTY_NOTICES.md"
                target="_blank"
                rel="noopener noreferrer"
                className="underline hover:text-foreground"
              >
                THIRD_PARTY_NOTICES.md
              </a>{' '}
              file.
            </p>
          </section>

          <section className="space-y-2">
            <h2 className="text-lg font-semibold text-foreground">Intellectual Property</h2>
            <p>
              &quot;Ravenswatch&quot; is a trademark of Passtech Games. All game assets, trademarks,
              and copyrights are property of their respective owners. This mod manager operates on
              local game files and does not distribute copyrighted content.
            </p>
          </section>
        </CardContent>
      </Card>

      <p className="mt-8 text-center text-xs text-muted-foreground">
        <Link href="/" className="underline hover:text-foreground">
          Home
        </Link>
        {' · '}
        <Link href="/privacy" className="underline hover:text-foreground">
          Privacy Policy
        </Link>
      </p>
    </main>
  );
}
