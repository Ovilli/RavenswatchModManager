import { useId, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { useT } from '../lib/i18n-react';
import { LOADER_LAUNCH_OPTIONS, setLaunchOptions } from '../lib/rsmm';
import { Button, CopyButton, useModalChrome } from './chrome';

/**
 * Linux/Proton: Wine ignores the loader's winhttp.dll unless Steam's launch
 * options carry the override, so script mods silently do nothing (#148).
 * Shown before a modded launch when the options lack it. Steam keeps launch
 * options in memory and rewrites localconfig.vdf on exit, so writing the file
 * only works with Steam closed — on a Steam Deck that is never, hence the
 * copy-and-paste path comes first.
 */
export function LaunchOptionsDialog({
  onLaunch,
  onCancel,
}: {
  onLaunch: () => void;
  onCancel: () => void;
}) {
  const t = useT();
  const titleId = useId();
  const cardRef = useRef<HTMLDivElement>(null);
  const onKeyDown = useModalChrome(cardRef, onCancel);
  const [writing, setWriting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const setForMe = async () => {
    setWriting(true);
    setError(null);
    try {
      const res = await setLaunchOptions();
      if (res?.ok) {
        onLaunch();
        return;
      }
      const out = `${res?.stdout ?? ''}\n${res?.stderr ?? ''}`;
      setError(
        /Steam is running/i.test(out)
          ? t(
              'Steam is running. Quit Steam completely, then try again — or paste the line yourself.',
            )
          : t('Could not write the launch options. Paste the line into Steam yourself.'),
      );
    } catch {
      setError(t('Could not write the launch options. Paste the line into Steam yourself.'));
    } finally {
      setWriting(false);
    }
  };

  return createPortal(
    <div
      // biome-ignore lint/a11y/useSemanticElements: see ai-disclosure.tsx — <dialog>'s top-layer backdrop conflicts with the app's overlay stacking
      role="dialog"
      aria-modal="true"
      aria-labelledby={titleId}
      className="fixed inset-0 z-[70] flex items-center justify-center p-4 animate-fade-in"
      onKeyDown={onKeyDown}
    >
      <div className="absolute inset-0 bg-pitch/80" />
      <div
        ref={cardRef}
        tabIndex={-1}
        className="grimoire-card grimoire-card--raised relative w-full max-w-xl p-6 focus:outline-none"
      >
        <h3 id={titleId} className="font-fraktur text-2xl text-parchment">
          {t('Steam launch options needed')}
        </h3>
        <p className="mt-3 font-serif-italic text-ash">
          {t(
            "On Linux, Proton ignores the mod loader unless Ravenswatch's launch options tell it to load it. Without them, script mods do nothing.",
          )}
        </p>
        <p className="mt-3 text-sm text-parchment">
          {t(
            'In Steam: right-click Ravenswatch → Properties → General → Launch Options, and paste:',
          )}
        </p>
        <div className="mt-2 flex items-center gap-2">
          <code className="font-mono min-w-0 flex-1 break-all border border-border px-2 py-1 text-sm text-parchment">
            {LOADER_LAUNCH_OPTIONS}
          </code>
          <CopyButton value={LOADER_LAUNCH_OPTIONS} />
        </div>
        {error ? <p className="mt-3 font-mono text-sm text-crimson">{error}</p> : null}
        <div className="mt-5 flex flex-wrap justify-end gap-2">
          <Button onClick={onCancel}>{t('Cancel')}</Button>
          <Button onClick={setForMe} disabled={writing}>
            {writing ? t('Writing…') : t('Set it for me (Steam closed)')}
          </Button>
          <Button variant="primary" onClick={onLaunch} disabled={writing}>
            {t("I've added it — launch")}
          </Button>
        </div>
      </div>
    </div>,
    document.body,
  );
}
