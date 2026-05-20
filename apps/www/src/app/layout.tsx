import '@rsmm/ui/styles.css';
import type { Metadata } from 'next';
import { Providers } from './providers';

export const metadata: Metadata = {
  title: 'Ravenswatch Mod Manager',
  description: 'Cross-platform mod manager for Ravenswatch — browser, Windows, macOS, Linux.',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="dark">
      <body>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
