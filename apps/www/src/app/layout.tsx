import type { Metadata } from 'next';
import Link from 'next/link';
import { Nav } from './nav';
import { Providers } from './providers';
import { VersionBadge } from './version-badge';
import './globals.css';

export const metadata: Metadata = {
  title: 'Ravenswatch Mod Manager',
  description: 'Cross-platform mod manager for Ravenswatch — browser, Windows, macOS, Linux.',
  icons: '/logo.png',
};

const footerLinks = [
  { href: '/download', label: 'Download' },
  { href: 'https://github.com/Ovilli/RavenswatchModManager', label: 'Source Code' },
  { href: '/registry', label: 'Registry' },
  { href: '/legal', label: 'Legal Notice' },
  { href: '/privacy', label: 'Privacy Policy' },
] as const;

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="dark">
      <body className="flex min-h-screen flex-col">
        <Nav versionBadge={<VersionBadge />} />
        <div className="flex-1">
          <Providers>{children}</Providers>
        </div>

        <footer className="border-t border-border/40">
          <div className="container mx-auto grid gap-8 px-6 py-12 sm:grid-cols-2 lg:grid-cols-4">
            {/* Brand */}
            <div className="space-y-3">
              <Link href="/" className="flex items-center gap-2.5">
                <img src="/logo.png" alt="Ravenswatch Mod Manager" className="h-8 w-8 rounded-md object-cover" />
                <span className="text-sm font-semibold text-foreground">
                  Ravenswatch Mod Manager
                </span>
              </Link>
              <p className="text-xs leading-relaxed text-muted-foreground">
                A small, open-source app for installing and managing mods for the game Ravenswatch
                by Passtech Games. Not affiliated with Passtech Games or NACON.
              </p>
            </div>

            {/* Links */}
            <div className="space-y-3">
              <h4 className="text-xs font-semibold uppercase tracking-wider text-foreground/60">
                Links
              </h4>
              <ul className="space-y-2">
                {footerLinks.map((link) => (
                  <li key={link.label}>
                    {link.href.startsWith('http') ? (
                      <a
                        href={link.href}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-sm text-muted-foreground transition-colors hover:text-foreground"
                      >
                        {link.label}
                      </a>
                    ) : (
                      <Link
                        href={link.href}
                        className="text-sm text-muted-foreground transition-colors hover:text-foreground"
                      >
                        {link.label}
                      </Link>
                    )}
                  </li>
                ))}
              </ul>
            </div>

            {/* Support */}
            <div className="space-y-3">
              <h4 className="text-xs font-semibold uppercase tracking-wider text-foreground/60">
                Support
              </h4>
              <ul className="space-y-2">
                {[
                  { href: 'https://github.com/Ovilli/RavenswatchModManager#readme', label: 'Documentation' },
                  { href: 'https://github.com/Ovilli/RavenswatchModManager/issues', label: 'Report Bug' },
                ].map((link) => (
                  <li key={link.label}>
                    <a
                      href={link.href}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-sm text-muted-foreground transition-colors hover:text-foreground"
                    >
                      {link.label}
                    </a>
                  </li>
                ))}
              </ul>
            </div>

            {/* Social */}
            <div className="space-y-3">
              <h4 className="text-xs font-semibold uppercase tracking-wider text-foreground/60">
                Social
              </h4>
              <ul className="space-y-2">
                {[
                  { href: 'https://github.com/Ovilli/RavenswatchModManager', label: 'GitHub' },
                ].map((link) => (
                  <li key={link.label}>
                    <a
                      href={link.href}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-sm text-muted-foreground transition-colors hover:text-foreground"
                    >
                      {link.label}
                    </a>
                  </li>
                ))}
              </ul>
            </div>
          </div>

          {/* Bottom bar */}
          <div className="border-t border-border/20">
            <div className="container mx-auto flex flex-col items-center justify-between gap-2 px-6 py-4 sm:flex-row">
              <p className="text-xs text-muted-foreground">
                &copy; {new Date().getFullYear()} | Ravenswatch Mod Manager. Not affiliated with
                Passtech Games or NACON.
              </p>
              <div className="flex items-center gap-3 text-xs text-muted-foreground">
                <Link href="/privacy" className="underline-offset-2 hover:text-foreground hover:underline">
                  Privacy Policy
                </Link>
                <span aria-hidden="true">·</span>
                <Link href="/legal" className="underline-offset-2 hover:text-foreground hover:underline">
                  Terms of Service
                </Link>
                <span aria-hidden="true">·</span>
                <Link href="/legal" className="underline-offset-2 hover:text-foreground hover:underline">
                  Transparency
                </Link>
              </div>
            </div>
          </div>
        </footer>
      </body>
    </html>
  );
}
