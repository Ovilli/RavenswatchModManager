import { createFileRoute } from '@tanstack/react-router';
import { Fleuron, MonoTag, Panel, SectionHeader, Crest, Button } from '../components/chrome';
import pkg from '../../package.json';

export const Route = createFileRoute('/about')({
  component: AboutPage,
});

function AboutPage() {
  const version = pkg.version ?? '0.0.0';

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <SectionHeader
        title="About"
        subtitle="A small grimoire to bind the changes you bring to Ravenswatch."
      />

      <Panel className="flex flex-col gap-4">
        <div className="flex items-center gap-4">
          <div className="brand-crest p-1">
            <Crest monogram="R" size="sm" />
          </div>
          <div>
            <h2 className="font-fraktur text-2xl text-parchment">Ravenswatch Mod Manager</h2>
            <p className="font-serif-italic text-ash">Version <span className="font-mono">{version}</span></p>
          </div>
        </div>

        <p className="font-serif-italic leading-relaxed text-parchment/90">
          RSMM is a community mod manager for Ravenswatch. It applies cooked-asset
          overrides and Lua-scripted mods without requiring manual edits to the game's
          install directory. Profiles let you keep a vanilla loadout for daily runs and a
          curated mod set for other playstyles.
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
              Contribute, report issues, or read developer notes in the repository.
            </p>
            <div className="flex gap-2">
              <Button
                type="button"
                size="sm"
                onClick={() => window.open('https://github.com/', '_blank')}
              >
                View repository
              </Button>
              <Button
                type="button"
                size="sm"
                variant="primary"
                onClick={() => window.open('/docs/GETTING_STARTED.md', '_blank')}
              >
                Read docs
              </Button>
            </div>
          </div>
        </div>
      </Panel>

      <Panel className="flex flex-col md:flex-row items-center justify-between gap-3">
        <div>
          <h4 className="font-fraktur text-base text-parchment">Credits</h4>
          <p className="text-smoke font-serif-italic">Created by the RSMM community · Licensed under the project license</p>
        </div>
        <div className="flex items-center gap-3">
          <MonoTag>v{version}</MonoTag>
          <Button
            type="button"
            size="sm"
            onClick={() => window.open('/LICENSE', '_blank')}
          >
            View license
          </Button>
        </div>
      </Panel>
    </div>
  );
}
