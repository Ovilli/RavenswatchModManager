import { createFileRoute } from '@tanstack/react-router';
import pkg from '../../package.json';
import { Crest, Fleuron, MonoTag, Panel, SectionHeader } from '../components/chrome';

export const Route = createFileRoute('/about')({
  component: AboutPage,
});

function AboutPage() {
  const version = pkg.version ?? '0.0.0';
  const buttonClass = 'btn-grim inline-flex items-center justify-center px-3 py-1.5 text-sm';

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <SectionHeader
        title="About"
        subtitle="A small grimoire to bind the changes you bring to Ravenswatch."
      />

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
                href="https://github.com/Ovilli/RavenswatchModManager/blob/main/docs/GETTING_STARTED.md"
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
