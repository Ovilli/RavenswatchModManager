import { createFileRoute } from '@tanstack/react-router';
import { Check, Copy, Download, Pencil, Plus, Trash2, Upload } from 'lucide-react';
import { useState } from 'react';
import { Fleuron, MonoTag, Panel, SectionHeader } from '../components/chrome';
import { useDialog, useToast } from '../components/toast';
import { isEnabledIn, useApp } from '../store';

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
  const dialog = useDialog();
  const toast = useToast();

  function onImport() {
    const id = importP(code);
    if (!id) {
      setImportError('Could not read that code. Check it and try again.');
      return;
    }

    setCode('');
    setImporting(false);
    setImportError(null);
    toast.push('Profile imported.', 'success');
  }

  function onImportBackup() {
    const result = importBackup(backupCode);
    if (!result) {
      setBackupError('Could not read that backup code. Check it and try again.');
      return;
    }
    setBackupCode('');
    setImportingBackup(false);
    setBackupError(null);
    toast.push('Backup imported.', 'success');
  }

  const onNewProfile = async () => {
    const name = await dialog.prompt({
      title: 'New profile',
      label: 'Name',
      initialValue: 'New Run',
      submitLabel: 'Create',
    });
    if (name?.trim()) create(name.trim());
  };

  const onRename = async (id: string, currentName: string) => {
    const name = await dialog.prompt({
      title: 'Rename profile',
      label: 'Name',
      initialValue: currentName,
      submitLabel: 'Save',
    });
    if (name?.trim()) rename(id, name.trim());
  };

  const onDelete = async (id: string, name: string) => {
    const ok = await dialog.confirm({
      title: 'Delete profile',
      body: `Delete profile "${name}"? This cannot be undone.`,
      confirmLabel: 'Delete',
      destructive: true,
    });
    if (ok) {
      remove(id);
      toast.push(`Profile "${name}" deleted.`);
    }
  };

  const onExport = async (id: string) => {
    const text = exportP(id);
    try {
      await navigator.clipboard.writeText(text);
      toast.push('Profile code copied to clipboard.', 'success');
    } catch {
      await dialog.prompt({
        title: 'Profile code',
        label: 'Copy this code to share the profile',
        initialValue: text,
        submitLabel: 'Close',
        multiline: true,
      });
    }
  };

  const onExportBackup = async () => {
    const text = exportBackup();
    try {
      await navigator.clipboard.writeText(text);
      toast.push('Backup code copied to clipboard.', 'success');
    } catch {
      await dialog.prompt({
        title: 'Backup code',
        label: 'Copy this code to restore the full app state',
        initialValue: text,
        submitLabel: 'Close',
        multiline: true,
      });
    }
  };

  return (
    <div className="space-y-6">
      <SectionHeader
        title="Profiles"
        subtitle="Different loadouts for different runs. Share one as a code."
        right={
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => setImporting((v) => !v)}
              className="flex items-center gap-2 border border-border px-3 py-2 hover:border-gilt/50"
            >
              <Upload className="h-4 w-4" /> Import
            </button>
            <button
              type="button"
              onClick={() => setImportingBackup((v) => !v)}
              className="flex items-center gap-2 border border-border px-3 py-2 hover:border-gilt/50"
            >
              <Upload className="h-4 w-4" /> Backup
            </button>
            <button
              type="button"
              onClick={onNewProfile}
              className="flex items-center gap-2 border border-crimson bg-crimson/80 px-3 py-2 text-parchment hover:bg-oxblood transition-colors duration-150"
            >
              <Plus className="h-4 w-4" /> New profile
            </button>
          </div>
        }
      />

      {importing ? (
        <Panel>
          <h3 className="font-fraktur text-lg text-parchment mb-2">Import profile</h3>
          <p className="font-serif-italic text-ash mb-3">Paste an exported profile code below.</p>
          <textarea
            value={code}
            onChange={(e) => setCode(e.target.value)}
            rows={4}
            className="font-mono w-full resize-none border border-border bg-pitch/60 p-3 text-parchment focus:border-gilt/60 focus:outline-none"
            placeholder="base64-encoded profile…"
          />
          {importError ? (
            <p className="text-sm text-crimson mt-2" role="alert">
              {importError}
            </p>
          ) : null}
          <div className="mt-3 flex justify-end gap-2">
            <button
              type="button"
              onClick={() => setImporting(false)}
              className="border border-border px-3 py-1.5 text-ash hover:text-parchment"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={onImport}
              className="border border-crimson bg-crimson/80 px-3 py-1.5 text-parchment hover:bg-oxblood"
            >
              Import
            </button>
          </div>
        </Panel>
      ) : null}

      {importingBackup ? (
        <Panel>
          <h3 className="font-fraktur text-lg text-parchment mb-2">Import backup</h3>
          <p className="font-serif-italic text-ash mb-3">
            Paste a full-state backup code to restore profiles and settings.
          </p>
          <textarea
            value={backupCode}
            onChange={(e) => setBackupCode(e.target.value)}
            rows={4}
            className="font-mono w-full resize-none border border-border bg-pitch/60 p-3 text-parchment focus:border-gilt/60 focus:outline-none"
            placeholder="base64-encoded backup…"
          />
          {backupError ? (
            <p className="text-sm text-crimson mt-2" role="alert">
              {backupError}
            </p>
          ) : null}
          <div className="mt-3 flex justify-end gap-2">
            <button
              type="button"
              onClick={() => setImportingBackup(false)}
              className="border border-border px-3 py-1.5 text-ash hover:text-parchment"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={onImportBackup}
              className="border border-crimson bg-crimson/80 px-3 py-1.5 text-parchment hover:bg-oxblood"
            >
              Import backup
            </button>
          </div>
        </Panel>
      ) : null}

      <Panel>
        <div className="flex items-center justify-between gap-3">
          <div>
            <h3 className="font-fraktur text-lg text-parchment mb-2">Backup</h3>
            <p className="font-serif-italic text-ash">
              Save or restore all profiles, the active profile, and settings.
            </p>
          </div>
          <button
            type="button"
            onClick={onExportBackup}
            className="flex items-center gap-1.5 border border-border px-3 py-2 text-sm text-ash hover:border-gilt/50 hover:text-parchment"
          >
            <Download className="h-3.5 w-3.5" /> Export backup
          </button>
        </div>
      </Panel>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        {profiles.map((p) => {
          const isActive = p.id === activeId;
          const enabled = p.loadOrder.filter((id) => isEnabledIn(p, id)).length;
          return (
            <article key={p.id} className="grimoire-card p-5">
              <header className="flex items-start justify-between gap-2">
                <div>
                  <h3 className="font-fraktur text-2xl text-parchment leading-none">{p.name}</h3>
                  <p className="font-mono mt-1 text-ash">
                    {enabled} enabled · {p.loadOrder.length} total
                  </p>
                </div>
                {isActive ? <MonoTag tone="crimson">active</MonoTag> : null}
              </header>

              <Fleuron className="my-4" />

              <ul className="font-serif-italic max-h-32 space-y-0.5 overflow-y-auto text-sm text-smoke">
                {p.loadOrder.length === 0 ? (
                  <li className="text-ash">No mods.</li>
                ) : (
                  p.loadOrder.map((id) => (
                    <li key={id} className={p.disabled.has(id) ? 'opacity-50' : ''}>
                      {id}
                    </li>
                  ))
                )}
              </ul>

              <div className="mt-4 flex flex-wrap gap-2">
                {!isActive ? (
                  <button
                    type="button"
                    onClick={() => setActive(p.id)}
                    className="flex items-center gap-1.5 border border-crimson bg-crimson/80 px-2.5 py-1.5 text-sm text-parchment hover:bg-oxblood"
                  >
                    <Check className="h-3.5 w-3.5" /> Activate
                  </button>
                ) : null}
                <button
                  type="button"
                  onClick={() => duplicate(p.id)}
                  className="flex items-center gap-1.5 border border-border px-2.5 py-1.5 text-sm text-ash hover:border-gilt/50 hover:text-parchment"
                >
                  <Copy className="h-3.5 w-3.5" /> Duplicate
                </button>
                <button
                  type="button"
                  onClick={() => onRename(p.id, p.name)}
                  className="flex items-center gap-1.5 border border-border px-2.5 py-1.5 text-sm text-ash hover:border-gilt/50 hover:text-parchment"
                >
                  <Pencil className="h-3.5 w-3.5" /> Rename
                </button>
                <button
                  type="button"
                  onClick={() => onExport(p.id)}
                  className="flex items-center gap-1.5 border border-border px-2.5 py-1.5 text-sm text-ash hover:border-gilt/50 hover:text-parchment"
                >
                  <Download className="h-3.5 w-3.5" /> Export
                </button>
                {profiles.length > 1 ? (
                  <button
                    type="button"
                    onClick={() => onDelete(p.id, p.name)}
                    className="ml-auto flex items-center gap-1.5 border border-border px-2.5 py-1.5 text-sm text-ash hover:border-crimson hover:text-crimson"
                  >
                    <Trash2 className="h-3.5 w-3.5" /> Delete
                  </button>
                ) : null}
              </div>
            </article>
          );
        })}
      </div>
    </div>
  );
}
