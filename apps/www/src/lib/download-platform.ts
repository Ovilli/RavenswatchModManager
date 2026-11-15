export type DownloadPlatform = 'Windows' | 'Linux' | 'unsupported' | 'unknown';

interface BrowserPlatform {
  platform: string;
  userAgent: string;
  userAgentData?: { platform?: string; mobile?: boolean };
}

/** Recommend a desktop installer only when the browser identifies a supported OS. */
export function detectDownloadPlatform(browser: BrowserPlatform): DownloadPlatform {
  const { userAgent, platform, userAgentData } = browser;
  // Android reports Linux, and Windows Phone reports Windows. Exclude mobile
  // devices and ChromeOS before matching either desktop platform.
  if (userAgentData?.mobile || /android|iphone|ipad|ipod|windows phone|cros/i.test(userAgent)) {
    return 'unsupported';
  }

  const hint = userAgentData?.platform?.toLowerCase();
  if (hint === 'windows') return 'Windows';
  if (hint === 'linux') return 'Linux';
  if (hint && hint !== 'unknown') return 'unsupported';

  const identity = `${platform} ${userAgent}`;
  if (/mac|iphone|ipad|ipod/i.test(identity)) return 'unsupported';
  if (/\bwin32\b|\bwin64\b|windows/i.test(identity)) return 'Windows';
  if (/linux/i.test(identity)) return 'Linux';
  return 'unknown';
}
