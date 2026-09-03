import { useQuery } from '@tanstack/react-query';
import { createFileRoute } from '@tanstack/react-router';
import { invoke } from '@tauri-apps/api/core';
import { Copy, Download, FolderOpen, Pencil, Plus, Trash2, Upload } from 'lucide-react';
import { useEffect, useState } from 'react';
import { Button, Fleuron, MonoTag, Panel, SectionHeader } from '../components/chrome';
import { CheckIcon } from '../components/icons/CheckIcon';
import { useDialog, useToast } from '../components/toast';
import { useT } from '../lib/i18n-react';
import { validateProfileName } from '../lib/profile-name';
import { listLocalMods } from '../lib/rsmm';
import { isSafeProfileId } from '../lib/untrusted-state';
import { getMod, isEnabledIn, splitProfileMods, useApp } from '../store';

export const Route = createFileRoute('/profiles')({
  component: ProfilesPage,
});

function ProfilesPage() {
  const profiles = useApp((s) => s.profiles);
  const activeId = useApp((s) => s.activeProfileId);
  const setActive = useApp((s) => s.setActiveProfile);
  const create = useApp((s) => s.createProfile);
  const duplicate = useApp((s) => s.duplicateProfile);
  const rename = useApp((s) => s.renameProfile);
  const remove = useApp((s) => s.deleteProfile);
  const exportP = useApp((s) => s.exportProfile);
  const importP = useApp((s) => s.importProfile);
  const exportBackup = useApp((s) => s.exportBackup);
  const importBackup = useApp((s) => s.importBackup);
  const [importing, setImporting] = useState(false);
  const [importingBackup, setImportingBackup] = useState(false);
  const [code, setCode] = useState('');
  const [backupCode, setBackupCode] = useState('');
  const [importError, setImportError] = useState<string | null>(null);
  const [backupError, setBackupError] = useState<string | null>(null);
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
    const modsRoot = useApp.getState().settings.modsDir?.trim();
    if (!modsRoot) {
      toast.push(t('Set a mods folder in Settings first'), 'error');
      return;
    }
    try {
      await invoke('open_profile_dir', { modsRoot, profileId });
    } catch (err) {
      toast.push(err instanceof Error ? err.message : String(err), 'error');
    }
  };

  function onImport() {
    const id = importP(code);
    if (!id) {
      setImportError(t('Could not read that code. Check it and try again.'));
      return;
    }

    setCode('');
    setImporting(false);
    setImportError(null);
    toast.push(t('Profile imported.'), 'success');
  }

  function onImportBackup() {
    const result = importBackup(backupCode);
    if (!result.ok) {
      setBackupError(result.reason);
      return;
    }
    setBackupCode('');
    setImportingBackup(false);
    setBackupError(null);
    toast.push(t('Backup imported.'), 'success');
  }

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

  const onExport = async (id: string) => {
    const text = exportP(id);
    try {
      await navigator.clipboard.writeText(text);
      toast.push(t('Profile code copied to clipboard.'), 'success');
    } catch {
      await dialog.prompt({
        title: t('Profile code'),
        label: t('Copy this code to share the profile'),
        initialValue: text,
        submitLabel: t('Close'),
        multiline: true,
      });
    }
  };

  const onExportBackup = async () => {
    const text = exportBackup();
    try {
      await navigator.clipboard.writeText(text);
      toast.push(t('Backup code copied to clipboard.'), 'success');
    } catch {
      await dialog.prompt({
        title: t('Backup code'),
        label: t('Copy this code to restore the full app state'),
        initialValue: text,
        submitLabel: t('Close'),
        multiline: true,
      });
    }
  };

  return (
    <div className="space-y-6">
      <SectionHeader
        title={t('Profiles')}
        subtitle={t('Different loadouts for different runs. Share one as a code.')}
        right={
          <div className="flex flex-wrap items-center justify-end gap-2">
            <Button type="button" onClick={() => setImporting((v) => !v)}>
              <Upload className="h-4 w-4" aria-hidden="true" /> {t('Import')}
            </Button>
            <Button type="button" onClick={() => setImportingBackup((v) => !v)}>
              <Upload className="h-4 w-4" aria-hidden="true" /> {t('Backup')}
            </Button>
            <Button type="button" variant="primary" onClick={onNewProfile}>
              <Plus className="h-4 w-4" aria-hidden="true" /> {t('New profile')}
            </Button>
          </div>
        }
      />

      {importing ? (
        <Panel>
          <h3 className="font-fraktur text-lg text-parchment mb-2">{t('Import profile')}</h3>
          <p className="font-serif-italic text-ash mb-3">
            {t('Paste an exported profile code below.')}
          </p>
          <textarea
            value={code}
            onChange={(e) => setCode(e.target.value)}
            rows={4}
            className="font-mono w-full resize-none border border-border bg-pitch/60 p-3 text-parchment focus:border-gilt/60 focus:outline-none"
            placeholder={t('base64-encoded profile…')}
          />
          {importError ? (
            <p className="text-sm text-crimson mt-2" role="alert">
              {importError}
            </p>
          ) : null}
          <div className="mt-3 flex justify-end gap-2">
            <Button type="button" size="sm" onClick={() => setImporting(false)}>
              {t('Cancel')}
            </Button>
            <Button type="button" size="sm" variant="primary" onClick={onImport}>
              {t('Import')}
            </Button>
          </div>
        </Panel>
      ) : null}

      {importingBackup ? (
        <Panel>
          <h3 className="font-fraktur text-lg text-parchment mb-2">{t('Import backup')}</h3>
          <p className="font-serif-italic text-ash mb-3">
            {t('Paste a full-state backup code to restore profiles and settings.')}
          </p>
          <textarea
            value={backupCode}
            onChange={(e) => setBackupCode(e.target.value)}
            rows={4}
            className="font-mono w-full resize-none border border-border bg-pitch/60 p-3 text-parchment focus:border-gilt/60 focus:outline-none"
            placeholder={t('base64-encoded backup…')}
          />
          {backupError ? (
            <p className="text-sm text-crimson mt-2" role="alert">
              {backupError}
            </p>
          ) : null}
          <div className="mt-3 flex justify-end gap-2">
            <Button type="button" size="sm" onClick={() => setImportingBackup(false)}>
              {t('Cancel')}
            </Button>
            <Button type="button" size="sm" variant="primary" onClick={onImportBackup}>
              {t('Import backup')}
            </Button>
          </div>
        </Panel>
      ) : null}

      <Panel>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="min-w-0">
            <h3 className="font-fraktur text-lg text-parchment mb-2">{t('Backup')}</h3>
            <p className="font-serif-italic text-ash">
              {t('Save or restore all profiles, the active profile, and settings.')}
            </p>
          </div>
          <Button type="button" size="sm" onClick={onExportBackup}>
            <Download className="h-3.5 w-3.5" aria-hidden="true" /> {t('Export backup')}
          </Button>
        </div>
      </Panel>

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
          card carries six actions plus a mod list. Splitting only once the
          window is genuinely wide keeps each card usable. */}
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        {profiles.map((p) => {
          const isActive = p.id === activeId;
          // Count what actually exists. A profile whose mods were deleted
          // outside the app still holds their ids, and reporting those as
          // "12 total" is what made empty profiles look full.
          const split = splitProfileMods(p);
          // Before the list is known, treat every id as present rather than
          // as missing: the same "we do not know" reading as `modsKnown`.
          const present = modsKnown ? split.present : p.loadOrder;
          const missing = modsKnown ? split.missing : [];
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
                    const mod = getMod(id);
                    // No mod on disk for this id: a half-finished install, a
                    // folder deleted outside the app, or a legacy API UUID.
                    // Say so instead of printing the raw id as if it were a
                    // real (merely disabled) mod.
                    if (!mod) {
                      // Only accuse the id of being absent once we have been
                      // told what IS on disk.
                      if (!modsKnown) {
                        return (
                          <li key={id} className="text-smoke" title={id}>
                            {id}
                          </li>
                        );
                      }
                      return (
                        <li key={id} className="text-crimson/80" title={id}>
                          {id} <span className="font-mono text-[11px]">{t('— not on disk')}</span>
                        </li>
                      );
                    }
                    return (
                      <li key={id} className={p.disabled.has(id) ? 'opacity-50' : ''}>
                        {mod.name}
                      </li>
                    );
                  })
                )}
              </ul>

              {missing.length > 0 ? (
                <button
                  type="button"
                  onClick={() => {
                    const removed = pruneMissing(p.id);
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
                <Button type="button" size="sm" onClick={() => duplicate(p.id)}>
                  <Copy className="h-3.5 w-3.5" aria-hidden="true" /> {t('Duplicate')}
                </Button>
                <Button type="button" size="sm" onClick={() => onRename(p.id, p.name)}>
                  <Pencil className="h-3.5 w-3.5" aria-hidden="true" /> {t('Rename')}
                </Button>
                <Button type="button" size="sm" onClick={() => onExport(p.id)}>
                  <Download className="h-3.5 w-3.5" aria-hidden="true" /> {t('Export')}
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
