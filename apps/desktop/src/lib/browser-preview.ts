import { inTauri } from './platform';

const SESSION_KEY = 'rsmm:library-preview';

/** Opt in once per browser tab; keep the preview through router navigation. */
function enabled(): boolean {
  if (!import.meta.env.DEV || typeof window === 'undefined' || inTauri()) return false;
  const requested = new URLSearchParams(window.location?.search).get('preview');
  try {
    if (requested === 'off') sessionStorage.removeItem(SESSION_KEY);
    if (requested === 'library') sessionStorage.setItem(SESSION_KEY, 'library');
    return requested === 'library' || sessionStorage.getItem(SESSION_KEY) === 'library';
  } catch {
    return requested === 'library';
  }
}

export const LIBRARY_PREVIEW = import.meta.env.DEV && enabled();

// The normal store can still handle every interaction, without reading or
// overwriting real profiles/settings. A full reload resets this scratch store.
const values = new Map<string, string>();
export const previewStorage = {
  getItem: (key: string) => values.get(key) ?? null,
  setItem: (key: string, value: string) => {
    values.set(key, value);
  },
  removeItem: (key: string) => {
    values.delete(key);
  },
};
