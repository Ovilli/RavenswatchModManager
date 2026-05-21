'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';

const navLinks = [
  { href: '/' as const, label: 'Home' },
  { href: '/registry' as const, label: 'Browse Registry' },
  { href: '/download' as const, label: 'Download' },
];

export function Nav() {
  const pathname = usePathname();

  const isActive = (href: string) => {
    if (href === '/') return pathname === '/';
    return pathname.startsWith(href);
  };

  return (
    <header className="sticky top-0 z-50 border-b border-border/40 bg-background/80 backdrop-blur-xl">
      <div className="container mx-auto flex items-center justify-between px-6 py-3">
        <Link href="/" className="flex items-center gap-2.5 shrink-0">
          <div className="brand-crest">
            <span className="font-fraktur text-lg">RM</span>
          </div>
          <span className="hidden text-sm font-medium text-foreground/90 md:inline">
            Ravenswatch Mod Manager
          </span>
        </Link>

        <nav className="hidden items-center gap-1 md:flex">
          {navLinks.map((link) => (
            <Link
              key={link.href}
              href={link.href}
              className={`rounded-lg px-3 py-1.5 text-sm transition-colors ${
                isActive(link.href)
                  ? 'bg-crimson/10 text-parchment'
                  : 'text-muted-foreground hover:bg-foreground/5 hover:text-foreground'
              }`}
            >
              {link.label}
            </Link>
          ))}
        </nav>

        <div className="flex items-center gap-3">
          <a
            href="https://github.com/Ovilli/RavenswatchModManager"
            target="_blank"
            rel="noopener noreferrer"
            className="hidden text-sm text-muted-foreground underline-offset-2 hover:text-foreground hover:underline sm:inline"
          >
            View Source
          </a>

          <span className="hidden rounded-md border border-border/60 px-2 py-0.5 font-mono text-[0.65rem] uppercase tracking-wider text-muted-foreground sm:inline">
            v0.1.0-beta.2
          </span>

          <Link
            href="/auth/signin"
            className="inline-flex items-center gap-1.5 rounded-lg bg-crimson px-3.5 py-1.5 text-sm font-medium text-white transition-colors hover:bg-crimson/90"
          >
            Sign In
          </Link>
        </div>
      </div>
    </header>
  );
}
