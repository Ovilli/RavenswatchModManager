'use client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { NavigationGuardProvider } from 'nextjs-nav-guard';
import { useState } from 'react';

export function Providers({ children }: { children: React.ReactNode }) {
  const [qc] = useState(
    () => new QueryClient({ defaultOptions: { queries: { staleTime: 30_000 } } }),
  );
  return (
    <NavigationGuardProvider>
      <QueryClientProvider client={qc}>{children}</QueryClientProvider>
    </NavigationGuardProvider>
  );
}
