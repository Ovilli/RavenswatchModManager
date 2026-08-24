import { buttonVariants } from '@rsmm/ui';
import { SpeedInsights } from '@vercel/speed-insights/next';
import { Github } from 'lucide-react';
import type { Metadata, Viewport } from 'next';
import { Cormorant_Garamond, EB_Garamond, JetBrains_Mono, UnifrakturCook } from 'next/font/google';
import Link from 'next/link';
import Script from 'next/script';
import { BanGate } from './components/ban-gate';
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

// The site's own name is not the thing people search for. Queries are
// "ravenswatch mods" / "ravenswatch mod manager", and a brand-only <title>
// ranked nowhere for either while Nexus pages titled "Ravenswatch Mods" took
// the whole first page. Lead with the query, keep the brand after the dash.
const SITE_TITLE = 'Ravenswatch Mods — Browse, Install & Manage | RSMM';
const SITE_DESCRIPTION =
  'Download and install Ravenswatch mods in one click. Free, open-source mod ' +
  'manager for Windows and Linux — textures, items, talents and Lua mods, all reversible.';

export const metadata: Metadata = {
  metadataBase: new URL('https://rsmm.me'),
  title: SITE_TITLE,
  description: SITE_DESCRIPTION,
  // Without this the home page emits no canonical at all, so the apex and www
  // hosts compete as separate URLs and split their own ranking signals.
  alternates: { canonical: '/' },
  icons: '/logo.png',
  // AdSense site-ownership verification (alongside the loader script).
  other: { 'google-adsense-account': 'ca-pub-9139637424510522' },
  // Site-wide social-card defaults. Per-mod / per-collection pages override
  // title/description/images in their own layout's generateMetadata.
  openGraph: {
    type: 'website',
    siteName: 'Ravenswatch Mod Manager',
    title: SITE_TITLE,
    description: SITE_DESCRIPTION,
    url: '/',
    images: [{ url: '/logo.png', alt: 'Ravenswatch Mod Manager' }],
  },
  twitter: {
    card: 'summary',
    title: SITE_TITLE,
    description: SITE_DESCRIPTION,
    images: ['/logo.png'],
  },
};

export const viewport: Viewport = {
  themeColor: '#0a0a0a',
};

const REPO = 'https://github.com/Ovilli/RavenswatchModManager';

/**
 * Footer navigation, grouped by what someone is actually looking for.
 *
 * One structure rather than a `footerLinks` array plus two inline ones: the
 * old shape put ten links in a "Links" column beside a "Support" column of two
 * and a "Social" column of one, and reached `/legal` three times under three
 * different names — "Legal Notice" in the list, then "Terms of Service" and
 * "Transparency" in the bottom bar, all the same page. Privacy was listed
 * twice for the same reason. Each destination now appears once across these
 * columns; Download and the repo also appear in the brand block, but as
 * actions rather than as a second navigation entry.
 */
const footerSections = [
  {
    title: 'Product',
    links: [
      { href: '/download', label: 'Download' },
      { href: '/registry', label: 'Mod Registry' },
      { href: '/c', label: 'Collections' },
      { href: '/guides', label: 'Guides' },
    ],
  },
  {
    title: 'Develop',
    links: [
      { href: '/modding', label: 'Modding Guide' },
      { href: 'https://docs.rsmm.me', label: 'Documentation' },
      { href: REPO, label: 'Source Code' },
      { href: `${REPO}/issues`, label: 'Report a Bug' },
    ],
  },
  {
    title: 'Project',
    links: [
      { href: '/about', label: 'About' },
      { href: '/contact', label: 'Contact' },
      { href: '/legal', label: 'Legal Notice' },
      { href: '/privacy', label: 'Privacy Policy' },
      { href: '/dmca', label: 'Content Policy' },
    ],
  },
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
        <Providers>
          <Nav versionBadge={<VersionBadge />} />
          <div className="flex-1">{children}</div>
          <BanGate />
        </Providers>

        <footer className="mt-16 border-t border-border/40">
          <div className="container mx-auto grid gap-10 px-6 py-12 md:grid-cols-[1.4fr_repeat(3,1fr)]">
            {/* Brand. Carries the one action the footer should still be able to
                start — a visitor who scrolled the whole page without clicking
                Download had, until now, nothing to click down here. */}
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
              <p className="max-w-xs text-xs leading-relaxed text-muted-foreground">
                A small, open-source app for installing and managing mods for Ravenswatch. Free,
                reversible, and Windows/Linux only.
              </p>
              <div className="flex items-center gap-2 pt-1">
                <Link
                  href="/download"
                  className={buttonVariants({ variant: 'outline', size: 'sm' })}
                >
                  Download
                </Link>
                <a
                  href={REPO}
                  target="_blank"
                  rel="noopener noreferrer"
                  aria-label="RSMM on GitHub"
                  className={buttonVariants({ variant: 'ghost', size: 'sm' })}
                >
                  <Github className="h-4 w-4" aria-hidden="true" />
                </a>
              </div>
            </div>

            {footerSections.map((section) => (
              <nav key={section.title} aria-label={section.title} className="space-y-3">
                <h4 className="text-xs font-semibold uppercase tracking-wider text-foreground/60">
                  {section.title}
                </h4>
                <ul className="space-y-2">
                  {section.links.map((link) => (
                    <li key={link.href}>
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
              </nav>
            ))}
          </div>

          {/* Bottom bar: copyright and the disclaimer only. The legal pages have
              their own column now, so repeating them here — under invented
              names that all pointed at /legal — bought nothing. */}
          <div className="border-t border-border/20">
            <div className="container mx-auto flex flex-col items-center justify-between gap-2 px-6 py-4 text-xs text-muted-foreground sm:flex-row">
              <p>&copy; {new Date().getFullYear()} Ravenswatch Mod Manager</p>
              <p>
                Not affiliated with Passtech Games or NACON. Ravenswatch is a trademark of its
                respective owners.
              </p>
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
