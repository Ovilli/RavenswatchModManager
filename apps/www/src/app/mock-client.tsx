import type { ModListItem } from '@rsmm/schemas';
import {
  AboutIcon,
  BrowseIcon,
  ConflictsIcon,
  LibraryIcon,
  ProfilesIcon,
  SettingsIcon,
} from './icons';

const NAV = [
  { icon: LibraryIcon, label: 'Library', active: true },
  { icon: BrowseIcon, label: 'Browse', active: false },
  { icon: ProfilesIcon, label: 'Profiles', active: false },
  { icon: ConflictsIcon, label: 'Conflicts', active: false },
  { icon: SettingsIcon, label: 'Settings', active: false },
  { icon: AboutIcon, label: 'About', active: false },
];

export function MockClient({ mods }: { mods: ModListItem[] }) {
  const displayMods = mods.slice(0, 4);

  return (
    <div className="mt-12 overflow-hidden rounded-xl border border-border/50 shadow-2xl shadow-black/30">
      <div className="flex h-[540px] w-full overflow-hidden bg-pitch">
        {/* ───── Sidebar (w-72) ───── */}
        <aside className="surface-grain hidden w-72 shrink-0 flex-col border-r border-border bg-pitch sm:flex">
          {/* Brand header */}
          <div className="px-5 pb-4 pt-5">
            <div className="flex items-center gap-3">
              <div className="flex h-14 w-14 items-center justify-center rounded-md border border-gilt/30 bg-crimson/20 text-gilt font-fraktur text-3xl leading-none">
                R
              </div>
              <div>
                <h1 className="font-fraktur text-3xl leading-none text-parchment">RSMM</h1>
                <p className="font-serif-italic mt-1 text-sm text-ash">Ravenswatch Mod Manager</p>
              </div>
            </div>
          </div>

          {/* Profile popover */}
          <div className="px-4 pb-3">
            <div className="flex items-center justify-between rounded-md border border-border bg-pitch/60 px-3 py-2">
              <div>
                <p className="font-mono text-[0.6rem] text-ash">profile</p>
                <p className="font-serif-italic text-sm text-parchment">Default</p>
              </div>
              <svg
                className="h-3.5 w-3.5 text-ash"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
                role="img"
                aria-label="Open"
              >
                <title>Open</title>
                <polyline points="6 9 12 15 18 9" />
              </svg>
            </div>
          </div>

          {/* Navigation */}
          <nav className="flex flex-1 flex-col gap-1 px-2 py-2">
            {NAV.map((item) => (
              <div
                key={item.label}
                className={`nav-link-grim group ${item.active ? 'data-active' : ''}`}
                data-active={item.active ? 'true' : 'false'}
              >
                <item.icon className="nav-icon" />
                <span className="font-serif-italic text-base">{item.label}</span>
              </div>
            ))}
          </nav>

          {/* Account strip */}
          <div className="border-t border-border px-4 py-3">
            <div className="flex items-center gap-2">
              <div className="flex h-6 w-6 items-center justify-center rounded-full border border-border bg-char text-[0.5rem] text-ash">
                ?
              </div>
              <span className="font-serif-italic text-xs text-ash">Signed out</span>
            </div>
          </div>

          {/* Promoted banner area */}
          <div className="px-4 pb-4">
            <div className="grimoire-card flex items-center justify-center px-4 py-6">
              <span className="font-serif-italic text-[0.6rem] text-ash">ad slot offline</span>
            </div>
          </div>
        </aside>

        {/* ───── Content area ───── */}
        <div className="flex flex-1 flex-col overflow-hidden">
          {/* Status strip */}
          <div className="surface-grain flex items-center justify-between gap-3 border-b border-border px-3 py-2 backdrop-blur-sm">
            <div className="flex items-center gap-4">
              <span className="font-fraktur text-lg text-parchment">Ravenswatch Mod Manager</span>
              <span className="font-serif-italic text-ash">
                Default <span className="text-ash/60">·</span> 2 profiles
              </span>
            </div>
            <div className="flex items-center gap-2">
              {/* Launch buttons */}
              <div className="flex items-center gap-2 rounded-md border border-border bg-pitch/40 px-1.5 py-1">
                <div className="flex items-center gap-1.5 rounded border border-border/50 px-2 py-1 hover:bg-oxblood/20 transition-colors cursor-default">
                  <svg
                    className="h-3.5 w-3.5 text-parchment"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="1.2"
                    role="img"
                    aria-label="Launch"
                  >
                    <title>Launch</title>
                    <circle cx="12" cy="12" r="10" />
                    <path d="M10 8l6 4-6 4V8z" fill="currentColor" />
                  </svg>
                  <span className="font-serif-italic text-[0.6rem] text-parchment">
                    Launch Vanilla
                  </span>
                </div>
                <div className="flex items-center gap-1.5 rounded border border-crimson/50 bg-crimson/15 px-2 py-1 cursor-default">
                  <svg
                    className="h-3.5 w-3.5 text-parchment"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="1.2"
                    role="img"
                    aria-label="Launch"
                  >
                    <title>Launch</title>
                    <circle cx="12" cy="12" r="10" />
                    <path d="M10 8l6 4-6 4V8z" fill="currentColor" />
                  </svg>
                  <span className="font-serif-italic text-[0.6rem] text-parchment">
                    Launch Modded
                  </span>
                </div>
              </div>
              {/* Stat pills */}
              <div className="flex items-center gap-1.5">
                <span className="stat-pill">
                  <strong className="text-parchment">3</strong>
                  <span>enabled</span>
                </span>
                <span className="stat-pill">
                  <strong className="text-parchment">1</strong>
                  <span>disabled</span>
                </span>
                <span className="stat-pill" data-tone="gilt">
                  <strong className="text-parchment">1</strong>
                  <span>updates</span>
                </span>
              </div>
            </div>
          </div>

          {/* Main content */}
          <main className="flex-1 overflow-y-auto px-6 py-6 md:px-8">
            <div className="mx-auto w-full max-w-7xl animate-page-in">
              {/* Section header */}
              <div className="flex items-end justify-between gap-6 pb-4">
                <div>
                  <h2 className="font-fraktur text-3xl text-parchment leading-none">Library</h2>
                  <p className="font-serif-italic mt-2 text-ash text-base">
                    4 mods in the local folder.
                  </p>
                </div>
                <div className="flex items-center gap-1.5 shrink-0">
                  {/* View toggle */}
                  <div className="flex items-center gap-1 rounded border border-border p-0.5">
                    <div className="rounded px-1.5 py-0.5 bg-parchment/10 border border-gilt/40">
                      <svg
                        className="h-3 w-3 text-gilt"
                        viewBox="0 0 24 24"
                        fill="currentColor"
                        role="img"
                        aria-label="Grid view"
                      >
                        <title>Grid view</title>
                        <rect x="3" y="3" width="8" height="8" rx="1" />
                        <rect x="13" y="3" width="8" height="8" rx="1" />
                        <rect x="3" y="13" width="8" height="8" rx="1" />
                        <rect x="13" y="13" width="8" height="8" rx="1" />
                      </svg>
                    </div>
                    <div className="rounded px-1.5 py-0.5">
                      <svg
                        className="h-3 w-3 text-ash"
                        viewBox="0 0 24 24"
                        fill="none"
                        stroke="currentColor"
                        strokeWidth="2"
                        role="img"
                        aria-label="List view"
                      >
                        <title>List view</title>
                        <line x1="3" y1="6" x2="21" y2="6" />
                        <line x1="3" y1="12" x2="21" y2="12" />
                        <line x1="3" y1="18" x2="21" y2="18" />
                      </svg>
                    </div>
                  </div>
                  {/* Add mod button */}
                  <div
                    className="btn-grim px-3 py-1.5 text-sm font-serif-italic cursor-default"
                    data-variant="primary"
                  >
                    + Add mod
                  </div>
                </div>
              </div>

              {/* Filter bar */}
              <div className="flex flex-wrap items-center gap-3 mb-6">
                <div className="relative flex-1 min-w-[220px]">
                  <svg
                    className="absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-ash"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    role="img"
                    aria-label="Search"
                  >
                    <title>Search</title>
                    <circle cx="11" cy="11" r="8" />
                    <line x1="21" y1="21" x2="16.65" y2="16.65" />
                  </svg>
                  <div className="input-grim w-full pl-9 text-sm font-serif-italic text-ash/60 cursor-text">
                    Search installed mods…
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  {(['all', 'enabled', 'disabled', 'outdated'] as const).map((s) => (
                    <div
                      key={s}
                      className={`btn-grim px-3 py-1.5 text-sm cursor-default ${
                        s === 'all' ? '' : ''
                      }`}
                      data-variant={s === 'all' ? 'gilt' : undefined}
                    >
                      {s}
                    </div>
                  ))}
                </div>
              </div>

              {/* Mod cards */}
              <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
                {displayMods.map((mod, i) => (
                  <div
                    key={mod.id}
                    className="grimoire-card flex flex-col gap-3 p-5 cursor-default transition-colors duration-150 hover:border-gilt/40"
                  >
                    {/* Cover image */}
                    {mod.imageUrl ? (
                      <div className="relative aspect-video w-full overflow-hidden rounded border border-border bg-pitch">
                        <img
                          src={mod.imageUrl}
                          alt=""
                          className="h-full w-full object-cover"
                          loading="lazy"
                        />
                      </div>
                    ) : (
                      <div className="cover-placeholder aspect-video w-full" />
                    )}
                    {/* Header row */}
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <p className="font-serif-italic text-xl leading-tight text-parchment truncate">
                          {mod.name}
                        </p>
                        <p className="font-mono mt-1 text-ash">
                          {mod.author ?? 'unknown'}
                          {mod.latestVersion ? ` · v${mod.latestVersion}` : ''}
                        </p>
                      </div>
                      <div
                        className="btn-grim px-3 py-1.5 text-sm cursor-default flex items-center gap-1.5"
                        data-variant="primary"
                      >
                        <svg
                          className="h-3.5 w-3.5"
                          viewBox="0 0 24 24"
                          fill="none"
                          stroke="currentColor"
                          strokeWidth="2"
                          strokeLinecap="round"
                          strokeLinejoin="round"
                          role="img"
                          aria-label="Install"
                        >
                          <title>Install</title>
                          <line x1="12" y1="5" x2="12" y2="19" />
                          <line x1="5" y1="12" x2="19" y2="12" />
                        </svg>
                        install
                      </div>
                    </div>
                    {/* Summary */}
                    {mod.summary ? (
                      <p className="font-serif-italic text-sm leading-snug text-smoke line-clamp-2">
                        {mod.summary}
                      </p>
                    ) : null}
                    {/* Footer */}
                    <div className="mt-auto flex items-center justify-between gap-2">
                      <div className="flex flex-wrap gap-1">
                        {mod.category ? (
                          <span className="font-mono text-[0.6rem] rounded border border-border px-1.5 py-0.5 text-smoke">
                            {mod.category}
                          </span>
                        ) : null}
                        <span className="font-mono text-[0.6rem] rounded border border-border px-1.5 py-0.5 text-smoke">
                          #{i + 1}
                        </span>
                      </div>
                      <span className="stat-pill">
                        <strong>{mod.rating != null ? `★ ${mod.rating.toFixed(1)}` : '—'}</strong>
                        <span>{mod.downloads.toLocaleString()} dl</span>
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </main>
        </div>
      </div>
    </div>
  );
}
