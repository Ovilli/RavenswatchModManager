import { useEffect, useState } from 'react';
import pkg from '../../package.json';
import { BUNDLED_CHANGELOG, type ChangelogEntry, loadChangelog } from '../lib/changelog';
import { useT } from '../lib/i18n-react';
import { ChangelogSection } from './changelog-dialog';
import { MonoTag, Panel } from './chrome';

/** Releases shown before the panel asks you to expand it. */
const NOTES_COLLAPSED = 1;

/**
 * The About content, as panels rather than a page.
 *
 * Rendered inside Settings' "About" tab — one place for "how is this thing
 * configured, and what is it". `/about` is kept as a redirect so an older link
 * still lands somewhere sensible.
 */
export function AboutPanels() {
  const t = useT();
  const version = pkg.version ?? '0.0.0';
  const [showAll, setShowAll] = useState(false);
  // Starts from this build's copy so the panel renders immediately, then swaps
  // in the published feed — which can carry notes for loader updates that never
  // had an app release to be compiled into.
  const [entries, setEntries] = useState<ChangelogEntry[]>(BUNDLED_CHANGELOG);

  useEffect(() => {
    let alive = true;
    void loadChangelog().then((list) => {
      if (alive) setEntries(list);
    });
    return () => {
      alive = false;
    };
  }, []);

  const visible = showAll ? entries : entries.slice(0, NOTES_COLLAPSED);
  const buttonClass = 'btn-grim inline-flex items-center justify-center px-3 py-1.5 text-sm';

  return (
    <div className="space-y-6">
      <Panel className="flex flex-col gap-4">
        <div className="flex items-start gap-3">
          <div>
            <h3 className="font-fraktur text-lg text-parchment">
              {t('AI assistance & reverse engineering')}
            </h3>
            <p className="font-serif-italic mt-1 text-ash">
              {t('Shown once on first launch, kept here for reference.')}
            </p>
          </div>
        </div>
        <p className="font-serif-italic leading-relaxed text-parchment/90">
          {t(
            'Ravenswatch ships no modding API, so every capability here was reverse-engineered from the shipped game with Ghidra, disassembly and pattern-mining tools, plus a great deal of in-game testing. An AI coding assistant (Claude) was one instrument in that toolchain, used for reading decompiler output, drafting analysis tooling and writing application code. It is not the author of the result.',
          )}
        </p>
        <p className="font-serif-italic leading-relaxed text-smoke">
          {t(
            'Nothing reaches your game on an unverified claim: engine addresses are resolved by byte-pattern scan against your own copy of the game and re-verified before the loader is planted, CI re-derives the generated loader and SDK artifacts and fails on drift, a capability is only marked confirmed once it has been proven in a real run, and the loader bundle is cryptographically signed. Every file RSMM replaces is backed up, and Restore returns the install to stock.',
          )}
        </p>
      </Panel>

      <Panel className="flex flex-col gap-4">
        <div className="flex items-baseline justify-between gap-3">
          <div className="min-w-0">
            <h3 className="font-fraktur text-lg text-parchment">{t('Release notes')}</h3>
            <p className="font-serif-italic mt-1 text-ash">
              {showAll
                ? t('Every release this build knows about ({n}).', { n: entries.length })
                : t('The latest release. Older ones are a click away.')}
            </p>
          </div>
          {entries.length > NOTES_COLLAPSED ? (
            <button
              type="button"
              onClick={() => setShowAll((v) => !v)}
              className="font-mono shrink-0 text-xs text-ash underline-offset-2 hover:text-parchment hover:underline"
            >
              {showAll ? t('Show less') : t('Show all {n}', { n: entries.length })}
            </button>
          ) : null}
        </div>
        {/* Bounded, because the feed is not. Release notes now come from a
            rolling channel that can carry up to fifty entries, so rendering
            them all made this page grow without limit and pushed the panels
            below it off the bottom. One release is what someone opening About
            actually wants; the rest scroll inside their own box. */}
        <div
          className={
            showAll
              ? 'flex max-h-[55vh] flex-col gap-6 overflow-y-auto pr-1'
              : 'flex flex-col gap-6'
          }
        >
          {visible.map((entry) => (
            <ChangelogSection key={entry.version} entry={entry} />
          ))}
        </div>
      </Panel>

      <Panel className="flex flex-col md:flex-row items-center justify-between gap-3">
        <div className="min-w-0">
          <h4 className="font-fraktur text-base text-parchment">{t('Credits')}</h4>
          <p className="text-smoke font-serif-italic">
            {t('Created by the RSMM community · Licensed under the project license')}
          </p>
          <p className="text-smoke font-serif-italic text-xs">{t('Logo by Arch')}</p>
        </div>
        <div className="flex items-center gap-3">
          <MonoTag>v{version}</MonoTag>
          <a
            href="https://github.com/Ovilli/RavenswatchModManager/blob/main/LICENSE"
            target="_blank"
            rel="noreferrer noopener"
            className={buttonClass}
          >
            {t('View license')}
          </a>
        </div>
      </Panel>
    </div>
  );
}
