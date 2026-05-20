import { createFileRoute } from '@tanstack/react-router';
import { Trash2 } from 'lucide-react';
import { useState } from 'react';
import { Fleuron, Panel, SectionHeader } from '../components/chrome';
import { useApp } from '../store';

export const Route = createFileRoute('/settings')({
  component: SettingsPage,
});

function SettingsPage() {
  const settings = useApp((s) => s.settings);
  const update = useApp((s) => s.updateSettings);
  const [newSource, setNewSource] = useState('');

  return (
    <div className="space-y-6">
      <SectionHeader title="Settings" subtitle="Where things live. How they look." />

      <Panel>
        <h3 className="font-fraktur text-xl text-parchment">Paths</h3>
        <Fleuron className="my-3" />
        <Field
          label="Game install"
          value={settings.gameDir}
          onChange={(v) => update({ gameDir: v })}
        />
        <Field
          label="Backup folder"
          value={settings.backupDir}
          onChange={(v) => update({ backupDir: v })}
        />
      </Panel>

      <Panel>
        <h3 className="font-fraktur text-xl text-parchment">Mod sources</h3>
        <Fleuron className="my-3" />
        <ul className="space-y-2">
          {settings.sources.map((src) => (
            <li
              key={src}
              className="flex items-center justify-between gap-3 border border-border px-3 py-2"
            >
              <span className="font-mono text-parchment break-all">{src}</span>
              <button
                type="button"
                onClick={() =>
                  update({ sources: settings.sources.filter((s) => s !== src) })
                }
                className="font-mono text-ash hover:text-crimson"
              >
                <Trash2 className="h-3.5 w-3.5" />
              </button>
            </li>
          ))}
        </ul>
        <div className="mt-3 flex items-center gap-2">
          <input
            value={newSource}
            onChange={(e) => setNewSource(e.target.value)}
            placeholder="https://example.invalid/registry"
            className="font-mono flex-1 border border-border bg-pitch/60 px-3 py-2 text-parchment placeholder:text-ash focus:border-gilt/60 focus:outline-none"
          />
          <button
            type="button"
            onClick={() => {
              const v = newSource.trim();
              if (!v) return;
              if (settings.sources.includes(v)) return;
              update({ sources: [...settings.sources, v] });
              setNewSource('');
            }}
            className="border border-crimson bg-crimson/80 px-3 py-2 text-parchment hover:bg-oxblood"
          >
            Add
          </button>
        </div>
      </Panel>

      <Panel>
        <h3 className="font-fraktur text-xl text-parchment">Appearance</h3>
        <Fleuron className="my-3" />
        <fieldset className="flex flex-col gap-2">
          <legend className="font-mono mb-2 text-ash">Density</legend>
          {(['cozy', 'compact'] as const).map((d) => (
            <label
              key={d}
              className="flex cursor-pointer items-center gap-2 text-parchment"
            >
              <input
                type="radio"
                name="density"
                checked={settings.density === d}
                onChange={() => update({ density: d })}
                className="accent-crimson"
              />
              <span className="font-serif-italic capitalize">{d}</span>
            </label>
          ))}
        </fieldset>
      </Panel>
    </div>
  );
}

function Field({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
}) {
  return (
    <label className="mb-3 block">
      <span className="font-mono mb-1 block text-ash">{label}</span>
      <input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="font-mono w-full border border-border bg-pitch/60 px-3 py-2 text-parchment focus:border-gilt/60 focus:outline-none"
      />
    </label>
  );
}
