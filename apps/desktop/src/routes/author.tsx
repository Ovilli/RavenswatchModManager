import { useMutation } from '@tanstack/react-query';
import { createFileRoute } from '@tanstack/react-router';
import { FileSearch, FlaskConical, Layers, Loader2 } from 'lucide-react';
import { useState } from 'react';
import { Button, MonoTag, Panel, SectionHeader } from '../components/chrome';
import { type CookedInfo, uncookInfo } from '../lib/rsmm';

export const Route = createFileRoute('/author')({
  component: AuthorPage,
});

function AuthorPage() {
  const [path, setPath] = useState('');
  const [info, setInfo] = useState<CookedInfo | null>(null);

  const inspect = useMutation({
    mutationFn: (p: string) => uncookInfo(p),
    onSuccess: (data) => setInfo(data),
    onError: () => setInfo(null),
  });

  return (
    <div className="space-y-6">
      <SectionHeader
        title="Author"
        subtitle="Inspect cooked Ravenswatch assets. Per-class schema reversal in progress — see docs/RE_NOTES.md."
      />

      <Panel>
        <div className="flex items-baseline justify-between gap-2">
          <h3 className="font-fraktur text-lg text-parchment">Inspect cooked file</h3>
          <MonoTag tone="gilt">.yqz / .tpi / .zux / .gen</MonoTag>
        </div>
        <p className="font-serif-italic mt-1 text-ash">
          Paste the absolute path to a cooked file under{' '}
          <span className="font-mono">DarkTalesResources/_Cooking/</span>. The container header,
          class registry, and section sizes are extracted by the rsmm sidecar.
        </p>

        <div className="mt-4 flex flex-col gap-3 sm:flex-row">
          <input
            type="text"
            value={path}
            onChange={(e) => setPath(e.target.value)}
            placeholder="/path/to/Cooking/.../File.yqz"
            className="font-mono flex-1 rounded-md border border-border bg-parchment-shadow px-3 py-2 text-parchment outline-none placeholder:text-ash focus:border-crimson"
            spellCheck={false}
          />
          <Button
            onClick={() => path.trim() && inspect.mutate(path.trim())}
            disabled={!path.trim() || inspect.isPending}
          >
            {inspect.isPending ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin" /> Inspecting
              </>
            ) : (
              <>
                <FileSearch className="h-4 w-4" /> Inspect
              </>
            )}
          </Button>
        </div>

        {inspect.error ? (
          <p className="mt-3 text-crimson">
            <span className="font-mono">{(inspect.error as Error).message}</span>
          </p>
        ) : null}
      </Panel>

      {info ? <InfoView info={info} /> : null}
    </div>
  );
}

function InfoView({ info }: { info: CookedInfo }) {
  return (
    <div className="space-y-4">
      <Panel>
        <div className="flex items-baseline justify-between gap-2">
          <h3 className="font-fraktur text-lg text-parchment">Container</h3>
          <div className="flex items-center gap-2">
            <MonoTag tone="gilt">{info.root_class}</MonoTag>
            <MonoTag tone={info.schema_status === 'stub' ? 'crimson' : 'gilt'}>
              schema: {info.schema_status}
            </MonoTag>
          </div>
        </div>
        <p className="font-mono mt-1 break-all text-ash">{info.path}</p>
        <dl className="font-mono mt-3 grid grid-cols-2 gap-x-6 gap-y-1 text-sm text-parchment sm:grid-cols-4">
          <Stat label="size" value={`${info.size} B`} />
          <Stat label="variant" value={info.variant} />
          <Stat label="flags" value={`0x${info.flags.toString(16)}`} />
          <Stat label="source ext" value={info.source_ext} />
        </dl>
      </Panel>

      <Panel>
        <div className="flex items-baseline justify-between gap-2">
          <h3 className="font-fraktur text-lg text-parchment">
            <Layers className="mr-1 inline h-4 w-4" /> Class registry ({info.classes.length})
          </h3>
        </div>
        <div className="mt-3 overflow-x-auto">
          <table className="font-mono w-full text-sm">
            <thead className="text-ash">
              <tr>
                <th className="py-1 pr-4 text-left">name</th>
                <th className="py-1 pr-4 text-left">uid</th>
                <th className="py-1 pr-4 text-left">version</th>
                <th className="py-1 pr-4 text-left">parent uid</th>
              </tr>
            </thead>
            <tbody>
              {info.classes.map((c) => (
                <tr key={c.uid + c.name} className="border-t border-border/40 text-parchment">
                  <td className="py-1 pr-4">{c.name}</td>
                  <td className="py-1 pr-4 text-ash">{c.uid}</td>
                  <td className="py-1 pr-4">
                    {c.version[0]}.{c.version[1]}
                  </td>
                  <td className="py-1 pr-4 text-ash">{c.parent}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>

      <Panel>
        <div className="flex items-baseline justify-between gap-2">
          <h3 className="font-fraktur text-lg text-parchment">
            <FlaskConical className="mr-1 inline h-4 w-4" /> Sections ({info.sections.length})
          </h3>
          <p className="font-serif-italic text-ash">
            Total {sum(info.sections.map((s) => s.size))} B
          </p>
        </div>
        <ul className="font-mono mt-3 grid grid-cols-2 gap-2 text-sm sm:grid-cols-4">
          {info.sections.map((s) => (
            <li
              key={s.index}
              className="flex items-baseline justify-between rounded-md border border-border bg-parchment-shadow/40 px-3 py-2"
            >
              <span className="text-ash">[{s.index}]</span>
              <span className="text-parchment">{s.size} B</span>
            </li>
          ))}
        </ul>
        <p className="font-serif-italic mt-3 text-sm text-ash">
          Extract a section's bytes with the CLI:{' '}
          <span className="font-mono">rsmm uncook --raw --section N {info.path}</span>
        </p>
      </Panel>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <>
      <dt className="text-ash">{label}</dt>
      <dd className="text-parchment">{value}</dd>
    </>
  );
}

function sum(xs: number[]): number {
  return xs.reduce((a, b) => a + b, 0);
}
