import { useNavigate } from '@tanstack/react-router';
import { Check, ChevronDown, Copy, Plus } from 'lucide-react';
import { useEffect, useId, useRef, useState } from 'react';
import { useApp } from '../store';
import { useDialog, useToast } from './toast';

export function ProfilePopover() {
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
      title: 'New profile',
      label: 'Name',
      initialValue: 'New Run',
      submitLabel: 'Create',
    });
    const trimmed = name?.trim();
    if (!trimmed) return;
    if (trimmed.length > 64) {
      toast.push('Profile names must be 64 characters or fewer.', 'error');
      return;
    }
    // Reject ASCII control characters but allow anything else (Unicode,
    // emoji, spaces, common punctuation) — profile names are display-only.
    for (const ch of trimmed) {
      const code = ch.codePointAt(0);
      if (code !== undefined && code < 0x20) {
        toast.push('Profile names may not contain control characters.', 'error');
        return;
      }
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
        className="flex w-full items-center justify-between border border-border bg-pitch/60 px-3 py-2 text-left hover:border-gilt/50 transition-colors duration-150"
      >
        <span>
          <span className="block font-mono text-ash">profile</span>
          <span className="font-serif-italic text-lg text-parchment">{active?.name}</span>
        </span>
        <ChevronDown className="h-4 w-4 text-ash" aria-hidden />
      </button>

      {open ? (
        <div
          id={menuId}
          role="menu"
          className="absolute left-0 right-0 top-full z-40 mt-1 grimoire-card animate-fade-in"
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
                  <span>
                    <span className="text-parchment">{p.name}</span>
                    <span className="font-mono ml-2 text-ash">{p.loadOrder.length} mods</span>
                  </span>
                  {p.id === activeId ? <Check className="h-4 w-4 text-crimson" /> : null}
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
              <Plus className="h-3.5 w-3.5" /> New
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
              <Copy className="h-3.5 w-3.5" /> Duplicate
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
              Manage profiles →
            </button>
          </div>
        </div>
      ) : null}
    </div>
  );
}
