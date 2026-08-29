import { useNavigate } from '@tanstack/react-router';
import { ChevronDown, Copy, Plus } from 'lucide-react';
import { useEffect, useId, useRef, useState } from 'react';
import { useT } from '../lib/i18n-react';
import { validateProfileName } from '../lib/profile-name';
import { useApp } from '../store';
import { CheckIcon } from './icons/CheckIcon';
import { useDialog, useToast } from './toast';

/**
 * @param compact  render for a toolbar rather than a sidebar column: one row
 *                 sized to its content instead of a two-line block filling the
 *                 available width.
 */
export function ProfilePopover({ compact = false }: { compact?: boolean } = {}) {
  const t = useT();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const profiles = useApp((s) => s.profiles);
  const activeId = useApp((s) => s.activeProfileId);
  const setActive = useApp((s) => s.setActiveProfile);
  const create = useApp((s) => s.createProfile);
  const duplicate = useApp((s) => s.duplicateProfile);
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
    <div ref={ref} className="relative">
      <button
        ref={triggerRef}
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={menuId}
        className={
          compact
            ? 'flex max-w-[18rem] items-center gap-2 border border-border bg-pitch/60 px-2.5 py-1 text-left transition-colors duration-150 hover:border-gilt/50'
            : 'flex w-full items-center justify-between border border-border bg-pitch/60 px-3 py-2 text-left transition-colors duration-150 hover:border-gilt/50'
        }
      >
        {compact ? (
          <>
            <span className="font-mono shrink-0 text-xs text-ash">{t('profile')}</span>
            <span
              className="min-w-0 truncate font-serif-italic text-parchment"
              title={active?.name}
            >
              {active?.name}
            </span>
          </>
        ) : (
          <span className="min-w-0 flex-1">
            <span className="block font-mono text-ash">{t('profile')}</span>
            <span
              className="block truncate font-serif-italic text-lg text-parchment"
              title={active?.name}
            >
              {active?.name}
            </span>
          </span>
        )}
        <ChevronDown className="h-4 w-4 shrink-0 text-ash" aria-hidden />
      </button>

      {open ? (
        <div
          id={menuId}
          role="menu"
          // Sidebar: match the trigger's column width. Toolbar: the trigger is
          // sized to a profile name, which is far too narrow to list several of
          // them, so the menu gets its own width and hangs from the left edge.
          className={
            compact
              ? 'grimoire-card animate-fade-in absolute left-0 top-full z-40 mt-1 w-72'
              : 'grimoire-card animate-fade-in absolute left-0 right-0 top-full z-40 mt-1'
          }
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
            <button
              type="button"
              role="menuitem"
              onClick={onNewProfile}
              className="flex flex-1 items-center justify-center gap-2 border border-border px-2 py-1.5 text-sm hover:border-gilt/50"
            >
              <Plus className="h-3.5 w-3.5" /> {t('New')}
            </button>
            <button
              type="button"
              role="menuitem"
              onClick={() => {
                if (active) duplicate(active.id);
                setOpen(false);
              }}
              className="flex flex-1 items-center justify-center gap-2 border border-border px-2 py-1.5 text-sm hover:border-gilt/50"
            >
              <Copy className="h-3.5 w-3.5" /> {t('Duplicate')}
            </button>
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
