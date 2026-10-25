import { Coffee } from 'lucide-react';
import { useState } from 'react';
import pkg from '../../package.json';
import { useT } from '../lib/i18n-react';
import { Button } from './chrome';

const LAUNCHES_KEY = 'rsmm:modded-launches';
const DISMISS_KEY = 'rsmm:support-nudge-dismissed';
/** Ask only once the app has proven itself, not on first run. */
const MIN_LAUNCHES = 3;

function read(key: string): string | null {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

function write(key: string, value: string): void {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    /* storage unavailable — nudge just stays hidden or reappears, harmless */
  }
}

/** Called after a successful modded launch. */
export function noteModdedLaunch(): void {
  write(LAUNCHES_KEY, String((Number(read(LAUNCHES_KEY)) || 0) + 1));
}

/**
 * One-line Ko-fi ask on the Library page. Hidden until the user has had
 * {@link MIN_LAUNCHES} successful modded launches; dismissing it hides it
 * until the next app version.
 */
export function SupportNudge() {
  const t = useT();
  const [visible, setVisible] = useState(
    () =>
      (Number(read(LAUNCHES_KEY)) || 0) >= MIN_LAUNCHES && read(DISMISS_KEY) !== pkg.version,
  );
  if (!visible) return null;

  const dismiss = () => {
    write(DISMISS_KEY, pkg.version);
    setVisible(false);
  };

  return (
    <aside className="ember-banner flex w-full items-center gap-3 px-4 py-3">
      <Coffee className="h-4 w-4 shrink-0 text-gilt" aria-hidden />
      <p className="flex-1 text-sm">
        {t('RSMM is free and made by one person. If it saves you time, a coffee keeps it going.')}
      </p>
      <a
        href="https://ko-fi.com/W7W41FW3YE"
        target="_blank"
        rel="noreferrer noopener"
        onClick={dismiss}
        className="btn-grim px-3 py-1.5 text-sm"
        data-variant="gilt"
      >
        {t('Support on Ko-fi')}
      </a>
      <Button type="button" size="sm" onClick={dismiss}>
        {t('Not now')}
      </Button>
    </aside>
  );
}
