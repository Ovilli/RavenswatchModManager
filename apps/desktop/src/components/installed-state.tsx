import { Check } from 'lucide-react';
import { useT } from '../lib/i18n-react';

/** A status label, without the hover width or disabled styling of an install button. */
export function InstalledState({ title }: { title?: string }) {
  const t = useT();
  return (
    <span
      className="installed-state inline-flex shrink-0 items-center gap-1.5 whitespace-nowrap text-sm font-medium text-white"
      title={title}
    >
      <span className="inline-flex h-4 w-4 shrink-0 items-center justify-center rounded-full bg-white text-pitch">
        <Check className="h-3 w-3" aria-hidden="true" />
      </span>
      {t('Installed')}
    </span>
  );
}
