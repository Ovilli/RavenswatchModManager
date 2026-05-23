import { Link, createFileRoute } from '@tanstack/react-router';
import { AlertTriangle, Check, Loader2, Package, UploadCloud } from 'lucide-react';
import { useMemo, useState } from 'react';
import {
  Button,
  CopyButton,
  EmptyState,
  Fleuron,
  MonoTag,
  Panel,
  SectionHeader,
  StatPill,
} from '../components/chrome';
import { ApiError } from '@rsmm/api-client';
import { api } from '../lib/api';
import { useSession } from '../lib/auth-client';
import {
  type PackResult,
  type UploadResult,
  packMod,
  uploadBytes,
} from '../lib/rsmm';
import { useApp } from '../store';

export const Route = createFileRoute('/upload')({
  component: UploadPage,
});

type Phase =
  | { kind: 'idle' }
  | { kind: 'packing' }
  | { kind: 'packed'; pack: PackResult }
  | { kind: 'requesting'; pack: PackResult }
  | { kind: 'uploading'; pack: PackResult; uploadUrl: string }
  | { kind: 'done'; pack: PackResult; versionId: string }
  | { kind: 'error'; message: string; details?: string; pack?: PackResult };

/**
 * Convert an `ApiError` from `api.mods.upload(...)` into a human-readable
 * `{message, details}` pair. The presign endpoint has a small set of
 * well-known failures and each deserves operator-specific guidance.
 */
function formatPresignError(err: unknown): { message: string; details?: string } {
  if (!(err instanceof ApiError)) {
    return {
      message: err instanceof Error ? err.message : 'presign request failed',
    };
  }
  const body = err.body as { error?: string } | null;
  const detail = body?.error;
  if (err.status === 401) {
    return {
      message: 'You need to sign in before publishing.',
      details: detail,
    };
  }
  if (err.status === 403) {
    return {
      message: 'That slug is owned by another account. Pick a different mod id.',
      details: detail,
    };
  }
  if (err.status === 409) {
    return {
      message:
        'A version with this exact number already exists. Bump `version` in your manifest and re-pack.',
      details: detail,
    };
  }
  if (err.status === 413) {
    return {
      message: 'Mod exceeds the 500 MB upload limit. Trim assets and re-pack.',
      details: detail,
    };
  }
  if (err.status === 503) {
    return {
      message:
        'The mod index is not configured for uploads on this deployment. The server admin needs to set the S3_BUCKET / S3_ACCESS_KEY_ID / S3_SECRET_ACCESS_KEY env vars (see apps/api/src/env.ts).',
      details: detail,
    };
  }
  return {
    message: detail ?? `Upload presign failed (HTTP ${err.status}).`,
  };
}

function fmtBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KiB`;
  if (n < 1024 * 1024 * 1024) return `${(n / (1024 * 1024)).toFixed(1)} MiB`;
  return `${(n / (1024 * 1024 * 1024)).toFixed(2)} GiB`;
}

function UploadPage() {
  const installed = useApp((s) => s.installed);
  const localMods = useApp((s) => s.localMods);
  const { data: session, isPending: sessionLoading } = useSession();
  const [modId, setModId] = useState<string>('');
  const [phase, setPhase] = useState<Phase>({ kind: 'idle' });

  // Sort installed mods by display name so the picker is predictable.
  const modOptions = useMemo(() => {
    return installed
      .map((id) => ({ id, name: localMods[id]?.name ?? id, version: localMods[id]?.version }))
      .sort((a, b) => a.name.localeCompare(b.name));
  }, [installed, localMods]);

  if (sessionLoading) {
    return (
      <div className="flex items-center gap-2 text-ash font-mono">
        <Loader2 className="h-4 w-4 animate-spin" /> Checking session…
      </div>
    );
  }

  if (!session) {
    return (
      <EmptyState
        title="Sign in to publish"
        body="Publishing a mod attaches your account as the owner of its slug. Sign in or create an account to continue."
        action={
          <Link to="/signin" className="btn-grim" data-variant="primary">
            Sign in
          </Link>
        }
      />
    );
  }

  if (modOptions.length === 0) {
    return (
      <EmptyState
        title="Nothing to publish yet"
        body="Drop a mod folder into your mods/ directory first, then come back."
      />
    );
  }

  const busy =
    phase.kind === 'packing' ||
    phase.kind === 'requesting' ||
    phase.kind === 'uploading';

  const doPack = async () => {
    if (!modId) return;
    setPhase({ kind: 'packing' });
    try {
      const result = await packMod(modId);
      if (!result || !result.ok) {
        setPhase({
          kind: 'error',
          message: result?.error ?? 'pack failed',
          details: result?.stderr ?? result?.stdout,
        });
        return;
      }
      setPhase({ kind: 'packed', pack: result });
    } catch (err) {
      setPhase({
        kind: 'error',
        message: err instanceof Error ? err.message : String(err),
      });
    }
  };

  const doPublish = async () => {
    if (phase.kind !== 'packed') return;
    const pack = phase.pack;
    if (!pack.slug || !pack.version || !pack.sha256 || !pack.sizeBytes || !pack.manifest) {
      setPhase({
        kind: 'error',
        message: 'pack metadata incomplete — try repacking',
        pack,
      });
      return;
    }
    setPhase({ kind: 'requesting', pack });
    let uploadUrl: string;
    let versionId: string;
    try {
      const presign = await api.mods.upload({
        slug: pack.slug,
        version: pack.version,
        sha256: pack.sha256,
        sizeBytes: pack.sizeBytes,
        manifest: pack.manifest as Parameters<typeof api.mods.upload>[0]['manifest'],
      });
      uploadUrl = presign.uploadUrl;
      versionId = presign.versionId;
    } catch (err) {
      setPhase({ kind: 'error', ...formatPresignError(err), pack });
      return;
    }
    setPhase({ kind: 'uploading', pack, uploadUrl });
    try {
      // PUT done CLI-side so the browser doesn't need bucket-side CORS.
      if (!pack.path) throw new Error('pack path missing');
      const upload = await uploadBytes(pack.path, uploadUrl);
      if (!upload || !upload.ok) {
        setPhase({
          kind: 'error',
          message: upload?.error ?? 'upload failed',
          details: upload?.status ? `HTTP ${upload.status}` : undefined,
          pack,
        });
        return;
      }
      setPhase({ kind: 'done', pack, versionId });
    } catch (err) {
      setPhase({
        kind: 'error',
        message: err instanceof Error ? err.message : 'upload failed',
        pack,
      });
    }
  };

  return (
    <div className="space-y-6">
      <SectionHeader
        title="Upload a mod"
        subtitle={`Publish a local mod folder to the public index. Signed in as ${
          session.user.name ?? session.user.email ?? 'you'
        }.`}
      />

      <Panel>
        <h3 className="font-fraktur text-lg text-parchment flex items-center gap-2">
          <Package className="h-5 w-5 text-gilt" /> Mod
        </h3>
        <Fleuron className="my-3" />
        <label className="font-serif-italic text-sm text-smoke" htmlFor="mod-select">
          Choose a mod from your local folder
        </label>
        <select
          id="mod-select"
          value={modId}
          onChange={(e) => {
            setModId(e.target.value);
            setPhase({ kind: 'idle' });
          }}
          disabled={busy}
          className="input-grim mt-2 w-full"
        >
          <option value="">— pick a mod —</option>
          {modOptions.map((m) => (
            <option key={m.id} value={m.id}>
              {m.name}
              {m.version ? ` · v${m.version}` : ''} ({m.id})
            </option>
          ))}
        </select>
        <div className="mt-4 flex flex-wrap items-center gap-2">
          <Button
            type="button"
            onClick={doPack}
            disabled={!modId || busy}
            variant="primary"
          >
            {phase.kind === 'packing' ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin" /> packing…
              </>
            ) : (
              <>
                <Package className="h-4 w-4" /> {phase.kind === 'packed' ? 're-pack' : 'pack'}
              </>
            )}
          </Button>
          {phase.kind === 'packed' && phase.pack.sizeBytes ? (
            <StatPill value={fmtBytes(phase.pack.sizeBytes)} label="zip size" />
          ) : null}
        </div>
      </Panel>

      {phase.kind === 'packed' || phase.kind === 'requesting' || phase.kind === 'uploading' ? (
        <Panel>
          <h3 className="font-fraktur text-lg text-parchment flex items-center gap-2">
            <UploadCloud className="h-5 w-5 text-gilt" /> Publish
          </h3>
          <Fleuron className="my-3" />
          <PackSummary pack={(phase as { pack: PackResult }).pack} />
          <div className="mt-4 flex flex-wrap items-center gap-2">
            <Button
              type="button"
              onClick={doPublish}
              disabled={phase.kind !== 'packed'}
              variant="primary"
            >
              {phase.kind === 'requesting' ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" /> requesting URL…
                </>
              ) : phase.kind === 'uploading' ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" /> uploading…
                </>
              ) : (
                <>
                  <UploadCloud className="h-4 w-4" /> publish
                </>
              )}
            </Button>
          </div>
        </Panel>
      ) : null}

      {phase.kind === 'done' ? (
        <Panel>
          <div className="flex items-start gap-3">
            <Check className="h-5 w-5 text-gilt shrink-0 mt-1" />
            <div className="flex-1 space-y-2">
              <h3 className="font-fraktur text-lg text-parchment">Published</h3>
              <p className="font-serif-italic text-smoke">
                Version {phase.pack.version} of <code className="font-mono">{phase.pack.slug}</code>{' '}
                is now live in the index.
              </p>
              <p className="font-mono text-xs text-ash">version id: {phase.versionId}</p>
              <div className="flex gap-2">
                <Link
                  to="/mod/$slug"
                  params={{ slug: phase.pack.slug ?? '' }}
                  className="btn-grim"
                  data-variant="primary"
                >
                  view in browser
                </Link>
                <Button type="button" onClick={() => setPhase({ kind: 'idle' })}>
                  upload another
                </Button>
              </div>
            </div>
          </div>
        </Panel>
      ) : null}

      {phase.kind === 'error' ? (
        <div className="ember-banner flex items-start gap-3 px-4 py-3">
          <AlertTriangle className="h-4 w-4 text-crimson shrink-0 mt-1" />
          <div className="flex-1 space-y-1">
            <p className="font-serif-italic text-base">{phase.message}</p>
            {phase.details ? (
              <pre className="font-mono text-xs text-ash whitespace-pre-wrap break-all">
                {phase.details}
              </pre>
            ) : null}
          </div>
          <CopyButton value={[phase.message, phase.details].filter(Boolean).join('\n\n')} />
          <Button type="button" size="sm" onClick={() => setPhase({ kind: 'idle' })}>
            dismiss
          </Button>
        </div>
      ) : null}
    </div>
  );
}

function PackSummary({ pack }: { pack: PackResult }) {
  return (
    <dl className="grid grid-cols-1 gap-2 md:grid-cols-2 font-mono text-sm">
      <Row label="slug" value={pack.slug} />
      <Row label="version" value={pack.version} />
      <Row label="size" value={pack.sizeBytes != null ? fmtBytes(pack.sizeBytes) : undefined} />
      <Row label="sha256" value={pack.sha256?.slice(0, 16) + '…'} />
      <Row label="name" value={pack.manifest?.name} />
      <Row
        label="tags"
        value={
          pack.manifest?.tags?.length ? (
            <span className="flex flex-wrap gap-1">
              {pack.manifest.tags.map((t) => (
                <MonoTag key={t} tone="default">
                  {t}
                </MonoTag>
              ))}
            </span>
          ) : (
            '—'
          )
        }
      />
    </dl>
  );
}

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-baseline gap-2">
      <dt className="text-ash w-24 shrink-0">{label}</dt>
      <dd className="text-parchment break-all">{value || '—'}</dd>
    </div>
  );
}
