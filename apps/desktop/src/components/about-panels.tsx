import { Cpu } from 'lucide-react';
import { useEffect, useState } from 'react';
import pkg from '../../package.json';
import { ChangelogSection } from './changelog-dialog';
import { Crest, Fleuron, MonoTag, Panel } from './chrome';
import { BUNDLED_CHANGELOG, type ChangelogEntry, loadChangelog } from '../lib/changelog';

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
        <div className="flex items-center gap-4">
          <Crest size="lg" iconSrc="/logo.png" iconAlt="Ravenswatch Mod Manager Tauri icon" />
          <div>
            <h2 className="font-fraktur text-2xl text-parchment">Ravenswatch Mod Manager</h2>
            <p className="font-serif-italic text-ash">
              Version <span className="font-mono">{version}</span>
            </p>
          </div>
        </div>

        <p className="font-serif-italic leading-relaxed text-parchment/90">
          RSMM is a community mod manager for Ravenswatch. It applies cooked-asset overrides and
          Lua-scripted mods without requiring manual edits to the game's install directory. Profiles
          let you keep a vanilla loadout for daily runs and a curated mod set for other playstyles.
        </p>

        <Fleuron className="my-2" />

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div>
            <h3 className="font-fraktur text-lg text-parchment mb-2">Key features</h3>
            <ul className="font-serif-italic space-y-2 text-smoke">
              <li>· Browse community mods and install in one click</li>
              <li>· Toggle individual mods on or off per profile</li>
              <li>· Export and share profiles as short codes</li>
              <li>· Detect file-level conflicts before launching</li>
            </ul>
          </div>

          <div>
            <h3 className="font-fraktur text-lg text-parchment mb-2">Get involved</h3>
            <p className="font-serif-italic text-smoke leading-relaxed mb-3">
              Contribute, report issues, join the community Discord, or read developer notes in the
              repository.
            </p>
            <div className="flex gap-2">
              <a
                href="https://github.com/Ovilli/RavenswatchModManager"
                target="_blank"
                rel="noreferrer noopener"
                className={buttonClass}
              >
                View repository
              </a>
              <a
                href="https://discord.gg/TSVdCaqd"
                target="_blank"
                rel="noreferrer noopener"
                className={buttonClass}
              >
                Discord
              </a>
              <a
                href="https://github.com/Ovilli/RavenswatchModManager/blob/main/docs/INSTALLATION.md"
                target="_blank"
                rel="noreferrer noopener"
                className={`${buttonClass} btn-grim-primary`}
                data-variant="primary"
              >
                Read docs
              </a>
            </div>
          </div>
        </div>
      </Panel>

      <Panel className="flex flex-col gap-4">
        <div className="flex items-start gap-3">
          <div>
            <h3 className="font-fraktur text-lg text-parchment">
              AI assistance & reverse engineering
            </h3>
            <p className="font-serif-italic mt-1 text-ash">
              Shown once on first launch, kept here for reference.
            </p>
          </div>
        </div>
        <p className="font-serif-italic leading-relaxed text-parchment/90">
          Ravenswatch ships no modding API, so every capability here was reverse-engineered from the
          shipped game with Ghidra, disassembly and pattern-mining tools, plus a great deal of
          in-game testing. An AI coding assistant (Claude) was one instrument in that toolchain,
          used for reading decompiler output, drafting analysis tooling and writing application
          code. It is not the author of the result.
        </p>
        <p className="font-serif-italic leading-relaxed text-smoke">
          Nothing reaches your game on an unverified claim: engine addresses are resolved by
          byte-pattern scan against your own copy of the game and re-verified before the loader is
          planted, CI re-derives the generated loader and SDK artifacts and fails on drift, a
          capability is only marked confirmed once it has been proven in a real run, and the loader
          bundle is cryptographically signed. Every file RSMM replaces is backed up, and Restore
          returns the install to stock.
        </p>
      </Panel>

      <Panel className="flex flex-col gap-4">
        <div className="flex items-baseline justify-between gap-3">
          <div>
            <h3 className="font-fraktur text-lg text-parchment">Release notes</h3>
            <p className="font-serif-italic mt-1 text-ash">
              {showAll
                ? `Every release this build knows about (${entries.length}).`
                : 'The latest release. Older ones are a click away.'}
            </p>
          </div>
          {entries.length > NOTES_COLLAPSED ? (
            <button
              type="button"
              onClick={() => setShowAll((v) => !v)}
              className="font-mono shrink-0 text-xs text-ash underline-offset-2 hover:text-parchment hover:underline"
            >
              {showAll ? 'Show less' : `Show all ${entries.length}`}
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
        <div>
          <h4 className="font-fraktur text-base text-parchment">Credits</h4>
          <p className="text-smoke font-serif-italic">
            Created by the RSMM community · Licensed under the project license
          </p>
        </div>
        <div className="flex items-center gap-3">
          <MonoTag>v{version}</MonoTag>
          <a
            href="https://github.com/Ovilli/RavenswatchModManager/blob/main/LICENSE"
            target="_blank"
            rel="noreferrer noopener"
            className={buttonClass}
          >
            View license
          </a>
        </div>
      </Panel>
    </div>
  );
}
