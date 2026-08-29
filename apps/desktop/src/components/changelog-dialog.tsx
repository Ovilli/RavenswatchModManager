import { ScrollText } from 'lucide-react';
import { useEffect, useState } from 'react';
import { createPortal } from 'react-dom';
import pkg from '../../package.json';
import { type ChangelogEntry, loadChangelog, pendingEntries } from '../lib/changelog';
import { changelogSeen, hasRunBefore, markChangelogSeen } from '../lib/first-run';
import { TParts, useT } from '../lib/i18n-react';
import { getAppVersion } from '../lib/updater';
import { AiDisclosureDialog } from './ai-disclosure';
import { Button, MonoTag } from './chrome';

/** One release's notes. Shared by the dialog and the About page. */
export function ChangelogSection({ entry }: { entry: ChangelogEntry }) {
  return (
    <section className="space-y-2">
      <header className="flex items-baseline gap-3">
        <h3 className="font-fraktur text-xl text-parchment">v{entry.version}</h3>
        <span className="flex-1 border-b border-dotted border-oxblood/40" aria-hidden />
        <MonoTag>{entry.date}</MonoTag>
      </header>
      {entry.summary ? (
        <p className="font-serif-italic text-ash leading-relaxed">{entry.summary}</p>
      ) : null}
      <ul className="space-y-2">
        {entry.highlights.map((line) => (
          <li key={line} className="flex items-start gap-2">
            <span className="mt-[0.4rem] h-1 w-1 shrink-0 rounded-full bg-gilt" aria-hidden />
            <span className="font-serif-italic leading-relaxed text-smoke">{line}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}

/**
 * "What's new" dialog, shown once per release the user has not yet seen.
 *
 * `enabled` is how the AI disclosure gets right of way on a first run: the two
 * dialogs would otherwise stack on the same launch, and the disclosure is the
 * one that must be read.
 *
 * The mark is written when the dialog is *dismissed*, not when it opens. An app
 * that is killed mid-read (or crashes on a bad mod during startup) should show
 * the notes again rather than swallow them.
 */
export function ChangelogDialog({ enabled }: { enabled: boolean }) {
  const t = useT();
  const [entries, setEntries] = useState<ChangelogEntry[]>([]);
  const [current, setCurrent] = useState<string>(pkg.version ?? '0.0.0');

  useEffect(() => {
    if (!enabled) return;
    let alive = true;
    void (async () => {
      // package.json is the compile-time fallback; the version baked into the
      // running bundle is what the user actually launched.
      //
      // The feed is read on every launch, not only after an app update: the
      // whole reason it lives outside the bundle is that a loader-channel fix
      // ships with no app release, and the note announcing it would otherwise
      // never be seen.
      const [version, available] = await Promise.all([
        getAppVersion()
          .catch(() => null)
          .then((v) => v || pkg.version || '0.0.0'),
        loadChangelog(),
      ]);
      if (!alive) return;
      const seen = changelogSeen();
      const pending = pendingEntries({
        entries: available,
        seen,
        current: version,
        hasRunBefore: hasRunBefore(),
      });
      setCurrent(version);
      if (pending.length === 0) {
        // Nothing to say — but still record where we are, so the *next* update
        // has a mark to compare against. Without this a fresh install would
        // stay unmarked forever and re-enter the "upgrading with no mark" path
        // on every future release.
        markChangelogSeen(version);
        return;
      }
      setEntries(pending);
    })();
    return () => {
      alive = false;
    };
  }, [enabled]);

  if (entries.length === 0) return null;

  const dismiss = () => {
    markChangelogSeen(current);
    setEntries([]);
  };

  return createPortal(
    <div
      // biome-ignore lint/a11y/useSemanticElements: see ai-disclosure.tsx — <dialog>'s top-layer backdrop conflicts with the app's overlay stacking
      role="dialog"
      aria-modal="true"
      aria-labelledby="changelog-title"
      className="fixed inset-0 z-[75] flex items-center justify-center p-4 animate-fade-in"
    >
      <div className="absolute inset-0 bg-pitch/85" onClick={dismiss} />
      <div className="grimoire-card relative flex max-h-[86vh] w-[min(600px,94vw)] flex-col p-6">
        <header className="flex items-start gap-3">
          <span className="mt-1 flex h-10 w-10 shrink-0 items-center justify-center rounded-full border border-crimson/40 bg-crimson/10">
            <ScrollText className="h-5 w-5 text-crimson" aria-hidden />
          </span>
          <div>
            <h2 id="changelog-title" className="font-fraktur text-2xl text-parchment">
              {t("What's new")}
            </h2>
            {/* The version is markup, not text, so the whole sentence stays
                one message and the styled node fills its placeholder. */}
            <p className="font-serif-italic mt-1 text-ash">
              <TParts
                text={t('RSMM updated to {version}.')}
                parts={{ version: <span className="font-mono text-gilt">v{current}</span> }}
              />
            </p>
          </div>
        </header>

        <div className="mt-4 min-h-0 flex-1 space-y-6 overflow-y-auto pr-1">
          {entries.map((e) => (
            <ChangelogSection key={e.version} entry={e} />
          ))}
        </div>

        <footer className="mt-5 flex items-center justify-end gap-2 border-t border-border pt-4">
          <Button type="button" size="sm" variant="primary" onClick={dismiss}>
            {t('Continue')}
          </Button>
        </footer>
      </div>
    </div>,
    document.body,
  );
}

/**
 * The first-render dialog stack, ordered.
 *
 * The disclosure runs first and holds the changelog back until it is
 * acknowledged, so the two never overlap on the launch where a brand-new user
 * would get both.
 */
export function FirstRunDialogs() {
  const [disclosureDone, setDisclosureDone] = useState(false);
  return (
    <>
      <AiDisclosureDialog onAcknowledged={() => setDisclosureDone(true)} />
      <ChangelogDialog enabled={disclosureDone} />
    </>
  );
}
