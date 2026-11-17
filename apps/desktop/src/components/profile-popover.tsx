import { useQueryClient } from '@tanstack/react-query';
import { useNavigate } from '@tanstack/react-router';
import { ChevronDown, Copy, Plus } from 'lucide-react';
import { useEffect, useId, useRef, useState } from 'react';
import { useT } from '../lib/i18n-react';
import { duplicateProfileWithMods } from '../lib/profile-mods';
import { validateProfileName } from '../lib/profile-name';
import { useApp } from '../store';
import { Button } from './chrome';
import { CheckIcon } from './icons/CheckIcon';
import { useDialog, useToast } from './toast';

/** Active game profile, beside the app logo. */
export function ProfilePopover() {
  const t = useT();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const profiles = useApp((s) => s.profiles);
  const activeId = useApp((s) => s.activeProfileId);
  const setActive = useApp((s) => s.setActiveProfile);
  const create = useApp((s) => s.createProfile);
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const dialog = useDialog();
  const toast = useToast();
  const active = profiles.find((p) => p.id === activeId) ?? profiles[0];
  const menuId = useId();

  useEffect(() => {
    if (!open) return;
    function onDoc(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') {
        setOpen(false);
        triggerRef.current?.focus();
      }
    }
    document.addEventListener('mousedown', onDoc);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onDoc);
      document.removeEventListener('keydown', onKey);
    };
  }, [open]);

  /**
   * Same as the Profiles page: the row AND the mod files. This button copied
   * only the row, so the copy (which becomes active) had no folder and both it
   * and the original looked empty in the Library.
   */
  const onDuplicate = async (id: string) => {
    const { copyError } = await duplicateProfileWithMods(id);
    if (copyError) {
      toast.push(
        t('Copied the profile, but not its mod files: {error}', { error: copyError }),
        'error',
      );
    }
    // The new profile went active before its folder existed, so a list read in
    // between saw nothing. Read it again now that the files are there.
    await queryClient.invalidateQueries({ queryKey: ['rsmm', 'list'] });
  };

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

  return (
    <div ref={ref} className="relative min-w-0 flex-1">
      <button
        ref={triggerRef}
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={menuId}
        className="flex min-h-11 w-full items-center gap-2 rounded px-2 text-left transition-colors duration-150 hover:bg-char/40"
      >
        <span
          className="min-w-0 truncate font-serif-italic text-lg text-parchment"
          title={active?.name}
        >
          {active?.name}
        </span>
        <ChevronDown className="h-4 w-4 shrink-0 text-ash" aria-hidden />
      </button>

      {open ? (
        <div
          id={menuId}
          role="menu"
          className="grimoire-card grimoire-card--raised animate-fade-in absolute -left-[3.25rem] top-full z-50 mt-2 w-64 max-w-[calc(100vw-2rem)]"
        >
          <ul className="max-h-72 overflow-y-auto py-1">
            {profiles.map((p) => (
              <li key={p.id}>
                <button
                  type="button"
                  role="menuitemradio"
                  aria-checked={p.id === activeId}
                  onClick={() => {
                    setActive(p.id);
                    setOpen(false);
                  }}
                  className="flex w-full items-center justify-between px-3 py-2 text-left hover:bg-oxblood/25"
                >
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-parchment" title={p.name}>
                      {p.name}
                    </span>
                    <span className="font-mono ml-2 text-ash">
                      {t.n(p.loadOrder.length, '{n} mod', '{n} mods')}
                    </span>
                  </span>
                  {p.id === activeId ? <CheckIcon className="h-5 w-5 text-crimson" /> : null}
                </button>
              </li>
            ))}
          </ul>
          <div className="border-t border-border p-2 flex gap-2">
            <Button
              type="button"
              size="sm"
              role="menuitem"
              onClick={onNewProfile}
              className="flex-1"
            >
              <Plus className="h-3.5 w-3.5" /> {t('New')}
            </Button>
            <Button
              type="button"
              size="sm"
              role="menuitem"
              onClick={() => {
                setOpen(false);
                if (active) void onDuplicate(active.id);
              }}
              className="flex-1"
            >
              <Copy className="h-3.5 w-3.5" /> {t('Duplicate')}
            </Button>
          </div>
          <div className="border-t border-border p-2">
            <button
              type="button"
              role="menuitem"
              onClick={() => {
                setOpen(false);
                navigate({ to: '/profiles' });
              }}
              className="font-mono w-full px-2 py-1 text-ash hover:text-parchment"
            >
              {t('Manage profiles →')}
            </button>
          </div>
        </div>
      ) : null}
    </div>
  );
}
