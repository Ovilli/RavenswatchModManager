import { Dialog } from '@base-ui/react/dialog';
import { Menu } from '@base-ui/react/menu';
import { Popover } from '@base-ui/react/popover';
import { useQueryClient } from '@tanstack/react-query';
import { ChevronDown, Copy, Download, MoreHorizontal, Plus, Trash2, X } from 'lucide-react';
import { useRef, useState } from 'react';
import { useT } from '../lib/i18n-react';
import { duplicateProfileWithMods } from '../lib/profile-mods';
import { validateProfileName } from '../lib/profile-name';
import { type Profile, isEnabledIn, useApp } from '../store';
import { Button } from './chrome';
import { CheckIcon } from './icons/CheckIcon';
import { useDialog, useToast } from './toast';
import './profile-popover.css';

/** Selection and management live beside the mod list they apply to. */
export function ProfilePopover() {
  const t = useT();
  const [open, setOpen] = useState(false);
  const [duplicating, setDuplicating] = useState(false);
  const duplicatePending = useRef(false);
  const [exported, setExported] = useState<{ name: string; code: string } | null>(null);
  const profiles = useApp((s) => s.profiles);
  const activeId = useApp((s) => s.activeProfileId);
  const setActive = useApp((s) => s.setActiveProfile);
  const create = useApp((s) => s.createProfile);
  const dialog = useDialog();
  const toast = useToast();
  const queryClient = useQueryClient();
  const active = profiles.find((p) => p.id === activeId) ?? profiles[0];

  const onNewProfile = async () => {
    setOpen(false);
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

  const onDelete = async (profile: Profile) => {
    setOpen(false);
    const ok = await dialog.confirm({
      title: t('Delete profile'),
      body: t('Delete profile "{name}"? This cannot be undone.', { name: profile.name }),
      confirmLabel: t('Delete'),
      destructive: true,
    });
    const state = useApp.getState();
    if (!ok || state.profiles.length <= 1) return;
    state.deleteProfile(profile.id);
    toast.push(t('Profile "{name}" deleted.', { name: profile.name }));
  };

  const onDuplicate = async (profile: Profile) => {
    if (duplicatePending.current) return;
    duplicatePending.current = true;
    setDuplicating(true);
    setOpen(false);
    try {
      const result = await duplicateProfileWithMods(profile.id);
      await queryClient.invalidateQueries({ queryKey: ['rsmm', 'list'] });
      if (result.copyError) {
        toast.push(
          t('Profile duplicated, but its mod files could not be copied: {error}', {
            error: result.copyError,
          }),
          'error',
        );
        return;
      }
      toast.push(t('Profile duplicated.'), 'success');
    } catch (error) {
      toast.push(error instanceof Error ? error.message : String(error), 'error');
    } finally {
      duplicatePending.current = false;
      setDuplicating(false);
    }
  };

  const onExport = (profile: Profile) => {
    setOpen(false);
    setExported({ name: profile.name, code: useApp.getState().exportProfile(profile.id) });
  };

  const copyExport = async () => {
    if (!exported) return;
    try {
      await navigator.clipboard.writeText(exported.code);
      toast.push(t('Profile code copied.'), 'success');
    } catch {
      toast.push(t('Could not copy. Select the code and copy it manually.'), 'error');
    }
  };

  return (
    <>
      <Popover.Root open={open} onOpenChange={setOpen}>
        <h2 className="font-fraktur text-3xl leading-none text-parchment">
          <Popover.Trigger className="flex min-h-11 max-w-full items-center gap-3 rounded text-left transition-colors duration-150 hover:text-gilt">
            <span className="min-w-0 truncate" title={active?.name}>
              {active?.name}
            </span>
            <ChevronDown className="h-5 w-5 shrink-0 text-ash" aria-hidden />
          </Popover.Trigger>
        </h2>
        <Popover.Portal>
          <Popover.Positioner sideOffset={8} align="start" className="z-50">
            <Popover.Popup
              className="profile-picker grimoire-card grimoire-card--raised"
              aria-label={t('Profiles')}
            >
              <ul className="max-h-72 overflow-y-auto p-1.5">
                {profiles.map((profile) => {
                  const enabled = profile.loadOrder.filter((id) => isEnabledIn(profile, id)).length;
                  return (
                    <li key={profile.id} className="profile-picker-row">
                      <button
                        type="button"
                        aria-pressed={profile.id === activeId}
                        disabled={duplicating}
                        onClick={() => {
                          setActive(profile.id);
                          setOpen(false);
                        }}
                        className="profile-picker-select"
                      >
                        <span className="profile-picker-check" aria-hidden="true">
                          {profile.id === activeId ? (
                            <CheckIcon className="h-5 w-5 text-crimson" />
                          ) : null}
                        </span>
                        <span className="min-w-0 flex-1">
                          <span className="block truncate text-parchment" title={profile.name}>
                            {profile.name}
                          </span>
                          <span className="profile-picker-count">
                            {t('{active} / {total} active', {
                              active: enabled,
                              total: profile.loadOrder.length,
                            })}
                          </span>
                        </span>
                      </button>
                      <Menu.Root>
                        <Menu.Trigger
                          className="profile-picker-more"
                          aria-label={t('Actions for {name}', { name: profile.name })}
                          disabled={duplicating}
                        >
                          <MoreHorizontal className="h-5 w-5" aria-hidden />
                        </Menu.Trigger>
                        <Menu.Portal>
                          <Menu.Positioner
                            side="right"
                            align="start"
                            sideOffset={6}
                            className="z-[60]"
                          >
                            <Menu.Popup
                              className="profile-actions grimoire-card grimoire-card--raised"
                              aria-label={t('Actions for {name}', { name: profile.name })}
                            >
                              <Menu.Item
                                className="profile-actions-item"
                                onClick={() => void onDuplicate(profile)}
                              >
                                <Copy className="h-4 w-4" aria-hidden /> {t('Duplicate')}
                              </Menu.Item>
                              <Menu.Item
                                className="profile-actions-item"
                                onClick={() => onExport(profile)}
                              >
                                <Download className="h-4 w-4" aria-hidden /> {t('Export')}
                              </Menu.Item>
                              <Menu.Separator className="my-1 border-t border-border" />
                              <Menu.Item
                                className="profile-actions-item profile-actions-item--danger"
                                disabled={profiles.length <= 1}
                                onClick={() => void onDelete(profile)}
                              >
                                <Trash2 className="h-4 w-4" aria-hidden /> {t('Delete')}
                              </Menu.Item>
                            </Menu.Popup>
                          </Menu.Positioner>
                        </Menu.Portal>
                      </Menu.Root>
                    </li>
                  );
                })}
              </ul>
              <div className="border-t border-border p-2">
                <Button
                  type="button"
                  size="sm"
                  onClick={() => void onNewProfile()}
                  className="w-full"
                  disabled={duplicating}
                >
                  <Plus className="h-4 w-4" aria-hidden /> {t('New profile')}
                </Button>
              </div>
            </Popover.Popup>
          </Popover.Positioner>
        </Popover.Portal>
      </Popover.Root>
      <Dialog.Root
        open={exported !== null}
        onOpenChange={(value) => {
          if (!value) setExported(null);
        }}
      >
        <Dialog.Portal>
          <Dialog.Backdrop className="fixed inset-0 z-[70] bg-pitch/80" />
          <Dialog.Popup className="grimoire-card grimoire-card--raised fixed left-1/2 top-1/2 z-[80] w-[min(30rem,92vw)] -translate-x-1/2 -translate-y-1/2 p-6">
            <Dialog.Title className="font-fraktur pr-8 text-2xl">
              {t('Export profile')}
            </Dialog.Title>
            <Dialog.Description className="mt-2 text-smoke">
              {t('Copy the share code for “{name}”.', { name: exported?.name ?? '' })}
            </Dialog.Description>
            <textarea
              readOnly
              aria-label={t('Profile share code')}
              value={exported?.code ?? ''}
              onFocus={(event) => event.currentTarget.select()}
              className="input-grim mt-4 h-28 w-full resize-none break-all font-mono text-xs"
            />
            <Button
              type="button"
              variant="primary"
              className="mt-4"
              onClick={() => void copyExport()}
            >
              <Copy className="h-4 w-4" aria-hidden /> {t('Copy code')}
            </Button>
            <Dialog.Close
              className="absolute right-4 top-4 rounded p-2 text-ash hover:text-parchment"
              aria-label={t('Close')}
            >
              <X className="h-4 w-4" aria-hidden />
            </Dialog.Close>
          </Dialog.Popup>
        </Dialog.Portal>
      </Dialog.Root>
    </>
  );
}
