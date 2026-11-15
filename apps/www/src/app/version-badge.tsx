import { version as checkoutVersion } from '../../../desktop/package.json';
import { getLatestRelease } from '../lib/releases';

export async function VersionBadge() {
  const release = await getLatestRelease();
  const version = release.tag ?? `v${checkoutVersion}`;
  return (
    <span className="inline-flex shrink-0 rounded-md border border-border/60 px-2 py-0.5 font-mono text-[0.65rem] uppercase tracking-wider text-muted-foreground">
      {version}
    </span>
  );
}
