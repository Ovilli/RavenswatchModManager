export type Platform = 'windows' | 'macos' | 'linux';

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
  } else if (p.includes('mac') || ua.includes('mac os')) {
    cached.platform = 'macos';
  } else {
    cached.platform = 'linux';
  }
  return cached.platform;
}

/** "⌘K" on macOS, "Ctrl+K" elsewhere. */
export function shortcutLabel(key: string): string {
  return getPlatform() === 'macos' ? `⌘${key.toUpperCase()}` : `Ctrl+${key.toUpperCase()}`;
}
