export type Platform = 'windows' | 'macos' | 'linux';

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

/** Lua scripting support is only available on Windows (requires native DLL) */
export function supportsLuaScripting(): boolean {
  return getPlatform() === 'windows';
}

/** Returns the download URL for the latest RSMM release for this platform */
export function getDownloadUrl(): string {
  const base = 'https://github.com/Ovilli/RavenswatchModManager/releases/latest';
  switch (getPlatform()) {
    case 'windows':
      return `${base}/RSMM-x64.msi`;
    case 'macos':
      return `${base}/RSMM-universal.dmg`;
    case 'linux':
      return `${base}/RSMM-x86_64.AppImage`;
  }
}
