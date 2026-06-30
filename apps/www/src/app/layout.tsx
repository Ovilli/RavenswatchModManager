import { SpeedInsights } from '@vercel/speed-insights/next';
import type { Metadata, Viewport } from 'next';
import { Cormorant_Garamond, EB_Garamond, JetBrains_Mono, UnifrakturCook } from 'next/font/google';
import Link from 'next/link';
import Script from 'next/script';
import { Nav } from './nav';
import { Providers } from './providers';
import { VersionBadge } from './version-badge';
import './globals.css';

// Self-hosted + preloaded via next/font (was a render-blocking CSS @import of
// Google Fonts that serialised the load waterfall). `swap` avoids invisible
// text; each exposes a CSS var consumed by globals.css.
const fraktur = UnifrakturCook({
  weight: '700',
  subsets: ['latin'],
  display: 'swap',
  variable: '--font-fraktur',
});
const cormorant = Cormorant_Garamond({
  weight: ['400', '500', '600'],
  style: ['normal', 'italic'],
  subsets: ['latin'],
  display: 'swap',
  variable: '--font-cormorant',
});
const garamond = EB_Garamond({
  weight: ['400', '500', '600'],
  style: ['normal', 'italic'],
  subsets: ['latin'],
  display: 'swap',
  variable: '--font-garamond',
});
const mono = JetBrains_Mono({
  weight: ['400', '500', '700'],
  subsets: ['latin'],
  display: 'swap',
  variable: '--font-mono',
});

export const metadata: Metadata = {
  metadataBase: new URL('https://rsmm.me'),
  title: 'Ravenswatch Mod Manager',
  description: 'Mod manager for Ravenswatch — browser, Windows, Linux.',
  icons: '/logo.png',
  // AdSense site-ownership verification (alongside the loader script).
  other: { 'google-adsense-account': 'ca-pub-9139637424510522' },
  // Site-wide social-card defaults. Per-mod / per-collection pages override
  // title/description/images in their own layout's generateMetadata.
  openGraph: {
    type: 'website',
    siteName: 'Ravenswatch Mod Manager',
    title: 'Ravenswatch Mod Manager',
    description: 'Mod manager for Ravenswatch — browser, Windows, Linux.',
    url: '/',
    images: [{ url: '/logo.png', alt: 'Ravenswatch Mod Manager' }],
  },
  twitter: {
    card: 'summary',
    title: 'Ravenswatch Mod Manager',
    description: 'Mod manager for Ravenswatch — browser, Windows, Linux.',
    images: ['/logo.png'],
  },
};

export const viewport: Viewport = {
  themeColor: '#0a0a0a',
};

const footerLinks = [
  { href: '/download', label: 'Download' },
  { href: 'https://github.com/Ovilli/RavenswatchModManager', label: 'Source Code' },
  { href: '/registry', label: 'Registry' },
  { href: '/guides', label: 'Guides' },
  { href: '/about', label: 'About' },
  { href: '/contact', label: 'Contact' },
  { href: '/legal', label: 'Legal Notice' },
  { href: '/privacy', label: 'Privacy Policy' },
  { href: '/dmca', label: 'Content Policy' },
] as const;

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html
      lang="en"
      className={`dark ${fraktur.variable} ${cormorant.variable} ${garamond.variable} ${mono.variable}`}
    >
      <body className="flex min-h-screen flex-col">
        {/* Sitewide structured data: Organization (logo in knowledge panel) +
            WebSite with a SearchAction (Google sitelinks search box pointing
            at the registry search). */}
        <script
          type="application/ld+json"
          // biome-ignore lint/security/noDangerouslySetInnerHtml: static, server-built JSON-LD — not user input.
          dangerouslySetInnerHTML={{
            __html: JSON.stringify({
              '@context': 'https://schema.org',
              '@graph': [
                {
                  '@type': 'Organization',
                  '@id': 'https://rsmm.me/#org',
                  name: 'Ravenswatch Mod Manager',
                  url: 'https://rsmm.me',
                  logo: 'https://rsmm.me/logo.png',
                },
                {
                  '@type': 'WebSite',
                  '@id': 'https://rsmm.me/#website',
                  name: 'Ravenswatch Mod Manager',
                  url: 'https://rsmm.me',
                  publisher: { '@id': 'https://rsmm.me/#org' },
                  potentialAction: {
                    '@type': 'SearchAction',
                    target: {
                      '@type': 'EntryPoint',
                      urlTemplate: 'https://rsmm.me/registry?q={search_term_string}',
                    },
                    'query-input': 'required name=search_term_string',
                  },
                },
              ],
            }),
          }}
        />
        <Nav versionBadge={<VersionBadge />} />
        <div className="flex-1">
          <Providers>{children}</Providers>
        </div>

        <footer className="border-t border-border/40">
          <div className="container mx-auto grid gap-8 px-6 py-12 sm:grid-cols-2 lg:grid-cols-4">
            {/* Brand */}
            <div className="space-y-3">
              <Link href="/" className="flex items-center gap-2.5">
                <img
                  src="/logo.png"
                  alt="Ravenswatch Mod Manager"
                  className="h-8 w-8 rounded-md object-cover"
                />
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
                  {
                    href: 'https://github.com/Ovilli/RavenswatchModManager#readme',
                    label: 'Documentation',
                  },
                  {
                    href: 'https://github.com/Ovilli/RavenswatchModManager/issues',
                    label: 'Report Bug',
                  },
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
                {[{ href: 'https://github.com/Ovilli/RavenswatchModManager', label: 'GitHub' }].map(
                  (link) => (
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
                  ),
                )}
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
                <Link
                  href="/privacy"
                  className="underline-offset-2 hover:text-foreground hover:underline"
                >
                  Privacy Policy
                </Link>
                <span aria-hidden="true">·</span>
                <Link
                  href="/legal"
                  className="underline-offset-2 hover:text-foreground hover:underline"
                >
                  Terms of Service
                </Link>
                <span aria-hidden="true">·</span>
                <Link
                  href="/legal"
                  className="underline-offset-2 hover:text-foreground hover:underline"
                >
                  Transparency
                </Link>
              </div>
            </div>
          </div>
        </footer>
        <SpeedInsights />
        {/* Google AdSense loader. Production only (Google rejects the script
            from localhost/preview). This both verifies the site during the
            AdSense review and serves Auto Ads once approved. */}
        {process.env.NODE_ENV === 'production' ? (
          <Script
            id="adsbygoogle-init"
            strategy="afterInteractive"
            async
            crossOrigin="anonymous"
            src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client=ca-pub-9139637424510522"
          />
        ) : null}
      </body>
    </html>
  );
}
