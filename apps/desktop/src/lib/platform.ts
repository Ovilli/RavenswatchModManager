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

/** "Ctrl+K" shortcut label (Windows + Linux). */
export function shortcutLabel(key: string): string {
  return `Ctrl+${key.toUpperCase()}`;
}
