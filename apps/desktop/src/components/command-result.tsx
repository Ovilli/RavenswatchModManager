import { AlertTriangle, CheckCircle2, CircleAlert, XCircle } from 'lucide-react';
import { explainError } from '../lib/errors';
import type { DoctorCheck, DoctorResult, LocalMod } from '../lib/rsmm';
import { CopyButton, MonoTag } from './chrome';

/**
 * Human rendering for command results.
 *
 * The bridge hands back parsed JSON (`rsmm.cli.json_bridge`), which is the
 * right wire format and the wrong thing to show a player. Each known shape
 * gets a real layout here; the raw payload stays one click away in the
 * `<details>` block for anyone filing a bug report.
 */

export type CommandResultKind = 'mods' | 'doctor' | 'run';

interface RunLike {
  ok: boolean;
  code: number;
  stdout: string;
  stderr: string;
}

function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null && !Array.isArray(v);
}

function isRunLike(v: unknown): v is RunLike {
  return isRecord(v) && typeof v.ok === 'boolean' && typeof v.code === 'number';
}

function isDoctorLike(v: unknown): v is DoctorResult {
  return isRunLike(v) && isRecord(v) && Array.isArray(v.checks);
}

function isModList(v: unknown): v is LocalMod[] {
  return Array.isArray(v) && v.every((m) => isRecord(m) && typeof m.id === 'string');
}

function stringify(value: unknown): string {
  if (typeof value === 'string') return value;
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

/** Sidecar stdout is a terminal transcript. Strip the ANSI colour the CLI
 * emits when it thinks it has a tty, so the panel doesn't show `[36m`. */
// biome-ignore lint/suspicious/noControlCharactersInRegex: stripping real ANSI escapes is the point
const ANSI = /\u001b\[[0-9;]*[A-Za-z]/g;

function cleanOutput(raw: string): string {
  return raw.replace(ANSI, '').trimEnd();
}

export function CommandResult({
  kind,
  result,
  error,
}: {
  kind: CommandResultKind;
  result: unknown;
  error?: string | null;
}) {
  if (error) {
    const { title, hint } = explainError(error);
    return (
      <div className="mt-3 space-y-2">
        <div className="border border-crimson/50 bg-crimson/10 p-3">
          <p className="flex items-center gap-2 text-parchment">
            <XCircle className="h-4 w-4 shrink-0 text-crimson" aria-hidden />
            <span className="font-serif-italic">{title}</span>
          </p>
          {hint ? <p className="font-serif-italic mt-1 text-sm text-ash">{hint}</p> : null}
        </div>
        <details className="border border-border/70">
          <summary className="font-mono cursor-pointer px-3 py-2 text-xs text-ash hover:text-parchment">
            Error detail
          </summary>
          <div className="flex items-start gap-2 border-t border-border/70 p-3">
            <pre className="max-h-64 flex-1 overflow-auto whitespace-pre-wrap font-mono text-xs text-crimson/90">
              {error}
            </pre>
            <CopyButton value={error} />
          </div>
        </details>
      </div>
    );
  }

  if (result == null) {
    return (
      <p className="font-serif-italic mt-3 text-ash">
        No response from rsmm. Check the game path in Settings, then try again.
      </p>
    );
  }

  return (
    <div className="mt-3 space-y-3">
      {kind === 'doctor' && isDoctorLike(result) ? (
        <DoctorView result={result} />
      ) : kind === 'mods' && isModList(result) ? (
        <ModListView mods={result} />
      ) : isRunLike(result) ? (
        <RunView result={result} />
      ) : (
        <pre className="overflow-auto whitespace-pre-wrap font-mono text-sm text-parchment/90">
          {stringify(result)}
        </pre>
      )}
      <RawDetails result={result} />
    </div>
  );
}

function RawDetails({ result }: { result: unknown }) {
  const raw = stringify(result);
  return (
    <details className="border border-border/70">
      <summary className="font-mono cursor-pointer px-3 py-2 text-xs text-ash hover:text-parchment">
        Raw output
      </summary>
      <div className="flex items-start gap-2 border-t border-border/70 p-3">
        <pre className="max-h-64 flex-1 overflow-auto whitespace-pre-wrap font-mono text-xs text-parchment/80">
          {raw}
        </pre>
        <CopyButton value={raw} />
      </div>
    </details>
  );
}

function StatusLine({
  ok,
  okText,
  failText,
}: {
  ok: boolean;
  okText: string;
  failText: string;
}) {
  return (
    <p className="flex items-center gap-2 text-parchment">
      {ok ? (
        <CheckCircle2 className="h-4 w-4 shrink-0 text-gilt" aria-hidden />
      ) : (
        <XCircle className="h-4 w-4 shrink-0 text-crimson" aria-hidden />
      )}
      <span className="font-serif-italic">{ok ? okText : failText}</span>
    </p>
  );
}

function OutputBlock({ label, text, tone }: { label: string; text: string; tone?: 'error' }) {
  const body = cleanOutput(text);
  if (!body) return null;
  return (
    <div>
      <p className="font-mono mb-1 text-xs text-ash">{label}</p>
      <pre
        className={`max-h-64 overflow-auto whitespace-pre-wrap font-mono text-sm ${
          tone === 'error' ? 'text-crimson' : 'text-parchment/90'
        }`}
      >
        {body}
      </pre>
    </div>
  );
}

function RunView({ result }: { result: RunLike }) {
  const stdout = cleanOutput(result.stdout ?? '');
  const stderr = cleanOutput(result.stderr ?? '');
  return (
    <div className="space-y-3">
      <StatusLine
        ok={result.ok}
        okText="Finished successfully."
        failText={`Failed with exit code ${result.code}.`}
      />
      {!stdout && !stderr ? (
        <p className="font-serif-italic text-ash">Nothing to report — rsmm printed no output.</p>
      ) : null}
      <OutputBlock label="Output" text={stdout} />
      <OutputBlock label="Errors" text={stderr} tone="error" />
    </div>
  );
}

function checkIcon(status: DoctorCheck['status']) {
  if (status === 'OK') return <CheckCircle2 className="h-4 w-4 shrink-0 text-gilt" aria-hidden />;
  if (status === 'WARN')
    return <CircleAlert className="h-4 w-4 shrink-0 text-parchment" aria-hidden />;
  return <AlertTriangle className="h-4 w-4 shrink-0 text-crimson" aria-hidden />;
}

function DoctorView({ result }: { result: DoctorResult }) {
  const checks = result.checks ?? [];
  const failed = checks.filter((c) => c.status === 'FAIL').length;
  const warned = checks.filter((c) => c.status === 'WARN').length;
  const passed = checks.length - failed - warned;

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <MonoTag tone="gilt">{passed} ok</MonoTag>
        {warned > 0 ? <MonoTag>{warned} warnings</MonoTag> : null}
        {failed > 0 ? <MonoTag tone="crimson">{failed} failed</MonoTag> : null}
      </div>
      <p className="font-serif-italic text-ash">
        {failed > 0
          ? 'Fix the failing checks below — mods will not apply cleanly until they pass.'
          : warned > 0
            ? 'Everything essential passed. The warnings are informational.'
            : 'Every check passed. Your setup is ready.'}
      </p>
      {result.gameUpdated ? (
        <p className="flex items-center gap-2 border border-border px-3 py-2 text-parchment">
          <CircleAlert className="h-4 w-4 shrink-0 text-parchment" aria-hidden />
          <span className="font-serif-italic">
            The game install changed since the last apply. Run Apply mods again before playing.
          </span>
        </p>
      ) : null}
      <ul className="space-y-1.5">
        {checks.map((c, i) => (
          <li
            // biome-ignore lint/suspicious/noArrayIndexKey: doctor returns a stable, identity-free list
            key={i}
            className="flex items-start gap-2"
          >
            {checkIcon(c.status)}
            <span className={c.ok ? 'text-ash' : 'text-parchment'}>{c.label}</span>
          </li>
        ))}
      </ul>
      <OutputBlock label="Errors" text={result.stderr ?? ''} tone="error" />
    </div>
  );
}

function ModListView({ mods }: { mods: LocalMod[] }) {
  if (mods.length === 0) {
    return (
      <p className="font-serif-italic text-ash">
        No mods in your mods folder yet. Install one from Browse.
      </p>
    );
  }
  const enabled = mods.filter((m) => m.enabled).length;
  return (
    <div className="space-y-3">
      <p className="font-serif-italic text-ash">
        {mods.length} mod{mods.length === 1 ? '' : 's'} on disk — {enabled} enabled.
      </p>
      <ul className="divide-y divide-border border border-border">
        {mods.map((mod) => (
          <li key={mod.id} className="flex flex-wrap items-center justify-between gap-2 px-3 py-2">
            <div className="min-w-0">
              <p className="text-parchment">
                {mod.name}
                <span className="font-mono ml-2 text-ash">v{mod.version}</span>
              </p>
              <p className="font-serif-italic truncate text-sm text-ash">
                {mod.summary ?? mod.author ?? mod.id}
              </p>
            </div>
            <MonoTag tone={mod.enabled ? 'gilt' : 'default'}>
              {mod.enabled ? 'enabled' : 'disabled'}
            </MonoTag>
          </li>
        ))}
      </ul>
    </div>
  );
}
