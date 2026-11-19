import { useQuery } from '@tanstack/react-query';
import { createFileRoute } from '@tanstack/react-router';
import { invoke } from '@tauri-apps/api/core';
import { FolderOpen, Pencil, Plus, Trash2 } from 'lucide-react';
import { useEffect } from 'react';
import { Button, Fleuron, MonoTag, Panel, SectionHeader } from '../components/chrome';
import { CheckIcon } from '../components/icons/CheckIcon';
import { useDialog, useToast } from '../components/toast';
import { useT } from '../lib/i18n-react';
import { validateProfileName } from '../lib/profile-name';
import { listLocalMods, listLocalModsForProfiles, modsRoot } from '../lib/rsmm';
import { isSafeProfileId } from '../lib/untrusted-state';
import { getMod, isEnabledIn, splitProfileMods, splitProfileModsAgainst, useApp } from '../store';

export const Route = createFileRoute('/profiles')({
  component: ProfilesPage,
});

function ProfilesPage() {
  const profiles = useApp((s) => s.profiles);
  const activeId = useApp((s) => s.activeProfileId);
  const setActive = useApp((s) => s.setActiveProfile);
  const create = useApp((s) => s.createProfile);
  const rename = useApp((s) => s.renameProfile);
  const remove = useApp((s) => s.deleteProfile);
  const activeProfileId = useApp((s) => s.activeProfileId);
  const syncLocalMods = useApp((s) => s.syncLocalMods);
  const pruneMissing = useApp((s) => s.pruneMissingMods);

  const localModsQuery = useQuery({
    queryKey: ['rsmm', 'list', activeProfileId],
    queryFn: listLocalMods,
    staleTime: 5_000,
  });

  useEffect(() => {
    if (localModsQuery.data) syncLocalMods(localModsQuery.data);
  }, [localModsQuery.data, syncLocalMods]);

  /**
   * Whether the on-disk mod list is actually known yet.
   *
   * Until the sidecar answers, `getMod(id)` is undefined for EVERYTHING, so
   * every entry in every profile rendered as crimson "not on disk" and the
   * "N missing" counter offered to prune the lot — a scary, wrong report on
   * first paint, and a permanent one if the CLI is broken. Absence of an
   * answer is not evidence of absence.
   */
  const modsKnown = localModsQuery.isSuccess;

  /**
   * What each OTHER profile has on disk. The sidecar lists one directory per
   * call (the active profile's), so `getMod` knows nothing about a profile that
   * is not active — judging those against it painted every one of their mods
   * "not on disk". Each is asked for its own directory instead.
   */
  const otherProfiles = profiles.filter((p) => p.id !== activeId);
  const otherIds = otherProfiles.map((p) => p.id);
  // ONE sidecar process for all of them. This used to be a query per profile, so
  // opening this screen started one cold sidecar for each inactive profile.
  const otherLists = useQuery({
    queryKey: ['rsmm', 'list', 'profiles', activeId, otherIds.join(',')],
    queryFn: () => listLocalModsForProfiles(otherIds),
    enabled: otherIds.length > 0,
    staleTime: 30_000,
    refetchOnWindowFocus: false,
  });
  const listedByProfile = new Map(
    otherProfiles.map((p) => [p.id, otherLists.data?.[p.id] ?? undefined] as const),
  );

  const t = useT();
  const dialog = useDialog();
  const toast = useToast();

  const onOpenFolder = async (profileId: string) => {
    // Creating and revealing the directory happens in Rust
    // (`profile_dir::open_profile_dir`), which re-validates the profile id,
    // expands `~` / `%VAR%`, and asserts the result stayed inside the mods
    // root. That let the default capability drop two grants this call used to
    // need — `mkdir` with arbitrary args, and `shell:allow-open` over
    // `file:///**` — neither of which anything else wanted.
    if (!isSafeProfileId(profileId)) {
      toast.push(t('Invalid profile id'), 'error');
      return;
    }
    try {
      // `modsRoot()` resolves an empty setting to the default folder, the one
      // every CLI call uses. Refusing here sent users to Settings to fill in a
      // field documented as "leave empty to use the default".
      await invoke('open_profile_dir', { modsRoot: modsRoot(), profileId });
    } catch (err) {
      toast.push(err instanceof Error ? err.message : String(err), 'error');
    }
  };

  const onNewProfile = async () => {
    const name = await dialog.prompt({
      title: t('New profile'),
      label: t('Name'),
      initialValue: t('New Run'),
      submitLabel: t('Create'),
    });
    const trimmed = name?.trim();
    if (!trimmed) return;
    const err = validateProfileName(trimmed);
    if (err) {
      toast.push(err, 'error');
      return;
    }
    create(trimmed);
  };

  const onRename = async (id: string, currentName: string) => {
    const name = await dialog.prompt({
      title: t('Rename profile'),
      label: t('Name'),
      initialValue: currentName,
      submitLabel: t('Save'),
    });
    const trimmed = name?.trim();
    if (!trimmed) return;
    const err = validateProfileName(trimmed);
    if (err) {
      toast.push(err, 'error');
      return;
    }
    rename(id, trimmed);
  };

  const onDelete = async (id: string, name: string) => {
    const ok = await dialog.confirm({
      title: t('Delete profile'),
      body: t('Delete profile "{name}"? This cannot be undone.', { name }),
      confirmLabel: t('Delete'),
      destructive: true,
    });
    if (ok) {
      remove(id);
      toast.push(t('Profile "{name}" deleted.', { name }));
    }
  };

  return (
    <div className="space-y-6">
      <SectionHeader
        title={t('Profiles')}
        subtitle={t('Different loadouts for different runs.')}
        right={
          <Button type="button" variant="primary" onClick={onNewProfile}>
            <Plus className="h-4 w-4" aria-hidden="true" /> {t('New profile')}
          </Button>
        }
      />

      {localModsQuery.isError ? (
        <Panel className="border-crimson">
          <p className="font-fraktur text-lg text-parchment">
            {t('Could not read the installed mods')}
          </p>
          <p className="font-data mt-2 break-words text-sm text-ash">
            {localModsQuery.error instanceof Error
              ? localModsQuery.error.message
              : String(localModsQuery.error)}
          </p>
          <p className="font-serif-italic mt-2 text-sm text-ash">
            {t('The mod names below may be incomplete until this succeeds.')}
          </p>
        </Panel>
      ) : null}

      {/* `xl`, not `md`. Tailwind breakpoints watch the VIEWPORT, but the
          sidebar takes 288px off this column before it starts: at the `md`
          width of 768px a "two-column" grid is two ~230px cards, and a profile
          card carries profile actions plus a mod list. Splitting only once the
          window is genuinely wide keeps each card usable. */}
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        {profiles.map((p) => {
          const isActive = p.id === activeId;
          // Count what actually exists. A profile whose mods were deleted
          // outside the app still holds their ids, and reporting those as
          // "12 total" is what made empty profiles look full.
          // The active profile is judged against the live registry; any other
          // against the list read from its own directory (see above).
          const listed = isActive ? undefined : listedByProfile.get(p.id);
          const known = isActive ? modsKnown : listed !== undefined;
          const split = isActive ? splitProfileMods(p) : splitProfileModsAgainst(p, listed ?? []);
          const listedById = new Map(
            (listed ?? []).flatMap(
              (m) =>
                [
                  [m.id, m],
                  [m.slug, m],
                ] as const,
            ),
          );
          const nameOf = (id: string) => (isActive ? getMod(id)?.name : listedById.get(id)?.name);
          // Before the list is known, treat every id as present rather than
          // as missing: the same "we do not know" reading as `modsKnown`.
          const present = known ? split.present : p.loadOrder;
          const missing = known ? split.missing : [];
          const enabled = present.filter((id) => isEnabledIn(p, id)).length;
          return (
            <article key={p.id} className="grimoire-card min-w-0 p-5">
              <header className="flex items-start justify-between gap-2 min-w-0">
                <div className="min-w-0 flex-1">
                  <h3
                    className="font-fraktur text-2xl text-parchment leading-none truncate"
                    title={p.name}
                  >
                    {p.name}
                  </h3>
                  <p className="font-mono mt-1 text-xs text-ash">
                    {t('{enabled} enabled · {present} on disk', {
                      enabled,
                      present: present.length,
                    })}
                    {missing.length > 0 ? (
                      <span className="text-crimson">
                        {' '}
                        · {t('{n} missing', { n: missing.length })}
                      </span>
                    ) : null}
                  </p>
                </div>
                {isActive ? <MonoTag tone="crimson">{t('active')}</MonoTag> : null}
              </header>

              <Fleuron className="my-4" />

              <ul className="font-serif-italic max-h-32 space-y-0.5 overflow-y-auto text-sm text-smoke">
                {p.loadOrder.length === 0 ? (
                  <li className="text-ash">{t('No mods.')}</li>
                ) : (
                  p.loadOrder.map((id) => {
                    const modName = nameOf(id);
                    // No mod on disk for this id: a half-finished install, a
                    // folder deleted outside the app, or a legacy API UUID.
                    // Say so instead of printing the raw id as if it were a
                    // real (merely disabled) mod.
                    if (modName === undefined) {
                      // Only accuse the id of being absent once we have been
                      // told what IS on disk.
                      if (!known) {
                        return (
                          <li key={id} className="text-smoke" title={id}>
                            {id}
                          </li>
                        );
                      }
                      return (
                        <li key={id} className="text-crimson" title={id}>
                          {id} <span className="font-mono text-xs">{t('— not on disk')}</span>
                        </li>
                      );
                    }
                    return (
                      <li key={id} className={p.disabled.has(id) ? 'opacity-50' : ''}>
                        {modName}
                      </li>
                    );
                  })
                )}
              </ul>

              {missing.length > 0 ? (
                <button
                  type="button"
                  onClick={() => {
                    const removed = pruneMissing(
                      p.id,
                      isActive ? undefined : (listed ?? []).flatMap((m) => [m.id, m.slug]),
                    );
                    toast.push(
                      t.n(
                        removed,
                        'Removed 1 entry with no mod on disk',
                        'Removed {n} entries with no mods on disk',
                      ),
                      'success',
                    );
                  }}
                  className="font-mono mt-3 w-full border border-crimson/60 px-2.5 py-1.5 text-xs text-crimson hover:bg-crimson/10"
                >
                  <span className="truncate">{t('Remove {n} missing', { n: missing.length })}</span>
                </button>
              ) : null}

              {/* ONE wrapping row, not a wrapping group pinned opposite a
                  fixed Delete: `justify-between` gave the group all the slack
                  and squeezed Delete against the card edge, and these were
                  hand-rolled buttons with none of `.btn-grim`'s `flex: none;
                  white-space: nowrap`, so their labels wrapped under their
                  icons. In a two-column grid at a 960px window each card is
                  only ~330px wide, which is where that first shows. */}
              <div className="mt-4 flex flex-wrap items-center gap-2">
                {!isActive ? (
                  <Button type="button" size="sm" variant="primary" onClick={() => setActive(p.id)}>
                    <CheckIcon className="h-4 w-4" aria-hidden="true" /> {t('Activate')}
                  </Button>
                ) : null}
                <Button type="button" size="sm" onClick={() => onRename(p.id, p.name)}>
                  <Pencil className="h-3.5 w-3.5" aria-hidden="true" /> {t('Rename')}
                </Button>
                <Button type="button" size="sm" onClick={() => onOpenFolder(p.id)}>
                  <FolderOpen className="h-3.5 w-3.5" aria-hidden="true" /> {t('Open folder')}
                </Button>
                {profiles.length > 1 ? (
                  <Button
                    type="button"
                    size="sm"
                    // Pushed to the end of the wrapping row rather than pinned
                    // opposite it, so it keeps its distance when there is room
                    // and simply wraps with the rest when there is not.
                    className="ml-auto hover:border-crimson hover:text-crimson"
                    onClick={() => onDelete(p.id, p.name)}
                  >
                    <Trash2 className="h-3.5 w-3.5" aria-hidden="true" /> {t('Delete')}
                  </Button>
                ) : null}
              </div>
            </article>
          );
        })}
      </div>
    </div>
  );
}
