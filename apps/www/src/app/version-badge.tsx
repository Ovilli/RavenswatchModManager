async function getLatestVersion(): Promise<string> {
  try {
    const res = await fetch(
      'https://api.github.com/repos/Ovilli/RavenswatchModManager/releases/latest',
      { next: { revalidate: 3600 } },
    );
    if (!res.ok) return 'v0.1.0-beta.2';
    const data = await res.json();
    return data.tag_name ?? 'v0.1.0-beta.2';
  } catch {
    return 'v0.1.0-beta.2';
  }
}

export async function VersionBadge() {
  const version = await getLatestVersion();
  return (
    <span className="hidden rounded-md border border-border/60 px-2 py-0.5 font-mono text-[0.65rem] uppercase tracking-wider text-muted-foreground sm:inline">
      {version}
    </span>
  );
}
