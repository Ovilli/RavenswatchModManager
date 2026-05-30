// The Zustand store uses `persist` backed by `localStorage`, which Node
// doesn't provide. Give it a minimal in-memory implementation so importing
// the store doesn't throw and persistence is a no-op the tests can ignore.
// (atob/btoa/TextEncoder/TextDecoder are already global in Node 18+.)
if (typeof globalThis.localStorage === 'undefined') {
  const store = new Map<string, string>();
  globalThis.localStorage = {
    getItem: (k) => (store.has(k) ? (store.get(k) as string) : null),
    setItem: (k, v) => {
      store.set(k, String(v));
    },
    removeItem: (k) => {
      store.delete(k);
    },
    clear: () => {
      store.clear();
    },
    key: (i) => [...store.keys()][i] ?? null,
    get length() {
      return store.size;
    },
  } as Storage;
}
