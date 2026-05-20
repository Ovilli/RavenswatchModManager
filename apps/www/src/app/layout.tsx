import type { Metadata } from 'next';
import Link from 'next/link';
import { Providers } from './providers';
import './globals.css';

export const metadata: Metadata = {
  title: 'Ravenswatch Mod Manager',
  description: 'Cross-platform mod manager for Ravenswatch — browser, Windows, macOS, Linux.',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="dark">
      <body className="flex min-h-screen flex-col">
        <div className="flex-1">
          <Providers>{children}</Providers>
        </div>
        <footer className="container mx-auto flex items-center justify-center gap-4 border-t border-border/40 px-6 py-4 text-xs text-muted-foreground">
          <span>&copy; {new Date().getFullYear()} Ravenswatch Mod Manager</span>
          <Link href="/legal" className="underline hover:text-foreground">Legal Notice</Link>
          <Link href="/privacy" className="underline hover:text-foreground">Privacy Policy</Link>
          <a
            href="https://github.com/Ovilli/RavenswatchModManager"
            target="_blank"
            rel="noopener noreferrer"
            className="underline hover:text-foreground"
          >
            GitHub
          </a>
        </footer>
      </body>
    </html>
  );
}
