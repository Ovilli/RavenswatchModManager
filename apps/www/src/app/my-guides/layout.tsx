import type { Metadata } from 'next';
import { noindex } from '../../lib/noindex';

export const metadata: Metadata = noindex;

export default function Layout({ children }: { children: React.ReactNode }) {
  return children;
}
