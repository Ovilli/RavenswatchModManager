import { cookies } from 'next/headers';
import { getApiUrl } from './api-url';
import { type Entity, fetchEntity } from './entity';

/** Keep public pages cached; retry private/delisted listings with the viewer's session. */
export async function fetchViewerEntity<T>(path: string): Promise<Entity<T>> {
  const publicResult = await fetchEntity<T>(path);
  if (publicResult.state !== 'missing') return publicResult;

  const cookie = (await cookies()).toString();
  if (!cookie) return publicResult;

  // Never put a private listing or its viewer permissions in Next's shared cache.
  try {
    const response = await fetch(`${getApiUrl()}${path}`, {
      headers: { cookie },
      cache: 'no-store',
    });
    if (response.status === 404 || response.status === 410) return { state: 'missing' };
    if (!response.ok) return { state: 'error' };
    return { state: 'ok', data: (await response.json()) as T };
  } catch {
    return { state: 'error' };
  }
}
