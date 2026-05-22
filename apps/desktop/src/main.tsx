import '@rsmm/ui/styles.css';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { RouterProvider, createRouter } from '@tanstack/react-router';
import { Component, type ErrorInfo, type ReactNode, StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { wireGlobalErrorHandlers } from './lib/telemetry';
import { routeTree } from './routeTree.gen';

wireGlobalErrorHandlers();

class RootErrorBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  override state = { error: null as Error | null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  override componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('Root render error:', error, info.componentStack);
  }

  override render() {
    if (this.state.error) {
      return (
        <div className="flex h-screen w-screen items-center justify-center bg-pitch p-8">
          <div className="max-w-md text-center space-y-4">
            <h1 className="font-fraktur text-3xl text-crimson">Something went wrong</h1>
            <pre className="font-mono text-sm text-ash whitespace-pre-wrap break-all">
              {this.state.error.message}
            </pre>
            <button
              type="button"
              onClick={() => window.location.reload()}
              className="border border-crimson px-4 py-2 text-parchment hover:bg-crimson/20"
            >
              Reload
            </button>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { retry: 1, staleTime: 30_000 },
  },
});

const router = createRouter({ routeTree, context: { queryClient } });

declare module '@tanstack/react-router' {
  interface Register {
    router: typeof router;
  }
}

const root = document.getElementById('root');
if (!root) throw new Error('missing #root');

createRoot(root).render(
  <StrictMode>
    <RootErrorBoundary>
      <QueryClientProvider client={queryClient}>
        <RouterProvider router={router} />
      </QueryClientProvider>
    </RootErrorBoundary>
  </StrictMode>,
);
