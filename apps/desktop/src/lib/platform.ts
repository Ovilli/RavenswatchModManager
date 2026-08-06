// RSMM desktop ships for Windows + Linux only (macOS support dropped).
export type Platform = 'windows' | 'linux';

/** True when the page is running inside the Tauri WebView, false in a
 * browser or under SSR/build. Multiple call sites duplicated this check;
 * keep it here so the global probe stays in one place. */
export function inTauri(): boolean {
  return (
    typeof window !== 'undefined' && ('__TAURI_INTERNALS__' in window || '__TAURI__' in window)
  );
}

const cached: { platform: Platform | null } = { platform: null };

export function getPlatform(): Platform {
  if (cached.platform) return cached.platform;
  const p = navigator.platform.toLowerCase();
  const ua = navigator.userAgent.toLowerCase();
  if (p.includes('win') || ua.includes('windows')) {
    cached.platform = 'windows';
  } else {
    cached.platform = 'linux';
  }
  return cached.platform;
}

/**
 * Join PATH entries with the platform's list separator.
 *
 * Windows separates PATH entries with `;`, not `:` — joining with a colon
 * there glues the prepended entry onto the first inherited one, so BOTH are
 * lost: the prepended directory never resolves and the first real PATH entry
 * is corrupted. Takes the platform explicitly so it is testable outside a
 * WebView (`getPlatform` reads `navigator`).
 */
export function joinPathEntries(entries: string[], platform: Platform): string {
  return entries.filter(Boolean).join(platform === 'windows' ? ';' : ':');
}

/** "Ctrl+K" shortcut label (Windows + Linux). */
export function shortcutLabel(key: string): string {
  return `Ctrl+${key.toUpperCase()}`;
}
