import { cn } from '@rsmm/ui';
import { Copy, EyeOff } from 'lucide-react';
import { useCallback, useEffect, useRef, useState } from 'react';
import type { ButtonHTMLAttributes, HTMLAttributes, ReactNode, RefObject } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { useT } from '../lib/i18n-react';

/**
 * Section divider. The class has always styled a rule with a gap and a text
 * colour in the middle of it, and the component rendered an empty div — so a
 * fleuron rule was two hairlines and no fleuron. The ornament is decorative and
 * hidden from assistive tech; the rules on either side carry the separation.
 */
export function Fleuron({
  className,
}: {
  className?: string;
}) {
  return (
    <div className={cn('rule-fleuron text-[0.9rem]', className)}>
      <span aria-hidden="true">❦</span>
    </div>
  );
}

/**
 * The keyboard half of a modal: Escape closes it, focus moves into it on open
 * and returns to whatever opened it on close.
 *
 * Extracted from `DialogModal` in components/toast.tsx, which was the only
 * place in the app doing this correctly. Everything else portals its overlay
 * to `document.body` — i.e. AFTER the trigger in DOM order — so without a
 * focus move, reaching the one button in a modal covering the whole window
 * meant tabbing through the entire app behind it, and Escape did nothing.
 *
 * @param focusRef  what to focus on open — the confirming button for a
 *   question, the card itself (give it `tabIndex={-1}`) for a notice.
 * @param onClose   Escape's action, or undefined for a modal that must be
 *   answered rather than dismissed.
 */
export function useModalChrome(
  focusRef: RefObject<HTMLElement | null>,
  onClose?: () => void,
): (e: React.KeyboardEvent) => void {
  useEffect(() => {
    const trigger = document.activeElement as HTMLElement | null;
    focusRef.current?.focus();
    return () => {
      // Optional-call: the trigger may have unmounted with the thing that
      // opened this, and a route change replaces it entirely.
      trigger?.focus?.();
    };
    // The ref identity is stable; re-running on it would re-steal focus.
  }, [focusRef]);

  return useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key !== 'Escape' || !onClose) return;
      e.preventDefault();
      e.stopPropagation();
      onClose();
    },
    [onClose],
  );
}

export function Crest({
  monogram = 'R',
  size = 'md',
  iconSrc,
  iconAlt = 'Tauri icon',
  className,
}: {
  monogram?: string;
  size?: 'sm' | 'md' | 'lg';
  iconSrc?: string;
  iconAlt?: string;
  className?: string;
}) {
  const sizeClass = size === 'sm' ? 'h-10 w-10' : size === 'lg' ? 'h-14 w-14' : 'h-12 w-12';
  return (
    <span className={cn('brand-crest', sizeClass, className)} aria-hidden>
      {iconSrc ? (
        <img
          src={iconSrc}
          alt={iconAlt}
          className="h-full w-full rounded-[inherit] object-contain p-1"
        />
      ) : (
        <span className="font-fraktur text-2xl leading-none">{monogram}</span>
      )}
    </span>
  );
}

export function Button({
  className,
  variant = 'default',
  size = 'md',
  children,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: 'default' | 'primary' | 'gilt' | 'danger';
  size?: 'sm' | 'md';
}) {
  return (
    <button
      className={cn('btn-grim', size === 'sm' ? 'px-3 py-1.5 text-sm' : undefined, className)}
      data-variant={variant === 'default' ? undefined : variant}
      {...props}
    >
      {children}
    </button>
  );
}

export function CopyButton({ value }: { value: string }) {
  const t = useT();
  const [copied, setCopied] = useState(false);
  const ref = useRef<HTMLTextAreaElement>(null);

  const copy = useCallback(() => {
    if (navigator.clipboard?.writeText) {
      navigator.clipboard.writeText(value).then(() => {
        setCopied(true);
        setTimeout(() => setCopied(false), 2000);
      });
    } else {
      const ta = ref.current;
      if (ta) {
        ta.select();
        document.execCommand('copy');
        setCopied(true);
        setTimeout(() => setCopied(false), 2000);
      }
    }
  }, [value]);

  return (
    <>
      <textarea
        ref={ref}
        value={value}
        readOnly
        aria-hidden="true"
        className="sr-only"
        tabIndex={-1}
      />
      <button
        type="button"
        onClick={copy}
        title={t('Copy error details')}
        aria-label={t('Copy error details to clipboard')}
        className={cn(
          'ml-auto inline-flex min-w-24 items-center justify-center gap-1.5 border border-border bg-pitch/70 px-3 py-1.5',
          'font-mono text-xs tracking-wider uppercase text-ash transition-colors duration-150',
          'hover:border-gilt/50 hover:text-parchment focus:outline-none focus:ring-2 focus:ring-gilt/40',
        )}
      >
        <Copy className="h-3.5 w-3.5" aria-hidden="true" />
        <span>{copied ? t('copied') : t('copy')}</span>
      </button>
    </>
  );
}

export function StatPill({
  label,
  value,
  tone = 'default',
  className,
}: {
  label?: ReactNode;
  value?: ReactNode;
  tone?: 'default' | 'gilt' | 'crimson';
  className?: string;
}) {
  return (
    <span className={cn('stat-pill', className)} data-tone={tone === 'default' ? undefined : tone}>
      {value != null ? <strong>{value}</strong> : null}
      {label != null ? <span>{label}</span> : null}
    </span>
  );
}

export function CoverPlaceholder({
  caption = 'cover.png',
  className,
}: {
  caption?: string;
  className?: string;
}) {
  return <div className={cn('cover-placeholder aspect-[16/9] w-full', className)}>{caption}</div>;
}

/**
 * Mod store-page cover. Renders the mod's asset if provided, falling
 * back to the parchment placeholder when no image is bundled.
 */
export function Cover({
  src,
  alt,
  caption,
  className,
  nsfw,
}: {
  src?: string | null;
  alt: string;
  caption?: string;
  className?: string;
  nsfw?: boolean;
}) {
  if (!src) return <CoverPlaceholder caption={caption} className={className} />;
  return (
    <div
      className={cn(
        'relative aspect-[16/9] w-full overflow-hidden border border-border bg-pitch',
        nsfw && 'group',
        className,
      )}
    >
      <img
        src={src}
        alt={alt}
        loading="lazy"
        className={cn(
          'h-full w-full object-cover',
          nsfw &&
            'blur-xl saturate-0 transition-all duration-300 group-hover:blur-none group-hover:saturate-100',
        )}
      />
      {nsfw ? (
        <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center gap-3 transition-opacity duration-300 group-hover:opacity-0">
          <EyeOff className="h-8 w-8 text-crimson/70" />
          <span className="rounded border border-crimson/30 bg-crimson/10 px-2 py-0.5 font-mono text-xs uppercase tracking-widest text-crimson/90">
            NSFW
          </span>
        </div>
      ) : null}
    </div>
  );
}

/**
 * Markdown renderer for mod store-page copy. Uses react-markdown +
 * remark-gfm so authored content matches what the website preview
 * shows (tables, task lists, headings 1–6, images, autolinks).
 * Element classes keep the grimoire palette intact.
 */
export function Markdown({ source, className }: { source: string; className?: string }) {
  const t = useT();
  return (
    <div className={cn('space-y-4 text-parchment/90', className)}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          h1: ({ node, ...props }) => (
            <h1 className="font-fraktur text-3xl text-parchment" {...props} />
          ),
          h2: ({ node, ...props }) => (
            <h2 className="font-fraktur text-2xl text-parchment" {...props} />
          ),
          h3: ({ node, ...props }) => (
            <h3 className="font-fraktur text-xl text-parchment" {...props} />
          ),
          h4: ({ node, ...props }) => (
            <h4 className="font-fraktur text-lg text-parchment" {...props} />
          ),
          h5: ({ node, ...props }) => (
            <h5 className="font-fraktur text-base text-parchment" {...props} />
          ),
          h6: ({ node, ...props }) => (
            <h6
              className="font-fraktur text-sm uppercase tracking-wider text-parchment"
              {...props}
            />
          ),
          p: ({ node, ...props }) => <p className="font-serif-italic leading-relaxed" {...props} />,
          a: ({ node, ...props }) => (
            <a
              target="_blank"
              rel="noreferrer noopener"
              className="text-gilt hover:underline"
              {...props}
            />
          ),
          ul: ({ node, ...props }) => (
            <ul className="font-serif-italic list-disc space-y-1 pl-6" {...props} />
          ),
          ol: ({ node, ...props }) => (
            <ol className="font-serif-italic list-decimal space-y-1 pl-6" {...props} />
          ),
          li: ({ node, ...props }) => <li {...props} />,
          blockquote: ({ node, ...props }) => (
            <blockquote
              className="font-serif-italic border-l-2 border-gilt/60 pl-4 text-ash"
              {...props}
            />
          ),
          code: ({ node, className, children, ...props }) => {
            const isInline = !/language-/.test(className ?? '');
            if (isInline) {
              return (
                <code
                  className="font-data border border-border bg-char/40 px-1 text-parchment"
                  {...props}
                >
                  {children}
                </code>
              );
            }
            return (
              <code className={cn('font-data', className)} {...props}>
                {children}
              </code>
            );
          },
          pre: ({ node, ...props }) => (
            <pre
              className="font-data overflow-x-auto border border-border bg-pitch/60 p-3 text-ash"
              {...props}
            />
          ),
          strong: ({ node, ...props }) => <strong className="text-parchment" {...props} />,
          em: ({ node, ...props }) => <em {...props} />,
          hr: ({ node, ...props }) => <hr className="border-oxblood/40" {...props} />,
          table: ({ node, ...props }) => (
            <div className="overflow-x-auto">
              <table className="w-full border-collapse text-sm" {...props} />
            </div>
          ),
          th: ({ node, ...props }) => (
            <th
              className="border border-oxblood/40 bg-char/30 px-2 py-1 text-left text-parchment"
              {...props}
            />
          ),
          td: ({ node, ...props }) => (
            <td className="border border-oxblood/40 px-2 py-1 align-top" {...props} />
          ),
          img: ({ node, alt, src, ...props }) => (
            <img
              {...props}
              src={src}
              alt={typeof alt === 'string' && alt.length > 0 ? alt : t('mod image')}
              className="max-w-full rounded border border-oxblood/30"
            />
          ),
        }}
      >
        {source}
      </ReactMarkdown>
    </div>
  );
}

export function MonoTag({
  children,
  tone = 'default',
  className,
}: {
  children: ReactNode;
  tone?: 'default' | 'crimson' | 'gilt';
  className?: string;
}) {
  return (
    <span
      className={cn(
        'font-mono inline-flex items-center border px-1.5 py-[1px]',
        tone === 'default' && 'border-border text-smoke',
        tone === 'crimson' && 'border-crimson/70 text-parchment bg-crimson/15',
        tone === 'gilt' && 'border-gilt/60 text-gilt',
        className,
      )}
    >
      {children}
    </span>
  );
}

/** @param compact  for a header inside a panel rather than at the top of a
 *                  page — smaller type, less air above and below. */
export function SectionHeader({
  title,
  subtitle,
  right,
  compact = false,
}: {
  title: string;
  subtitle?: string;
  right?: ReactNode;
  compact?: boolean;
}) {
  return (
    <header
      className={cn(
        // Wrapping, not just `justify-between`. The right slot is `shrink-0`
        // (a button group must never be squashed into its label), so on a
        // narrow window the row could only grow past the page instead of
        // giving. The sidebar makes that closer than it looks: at a 960px
        // window the content area is ~670px, while Tailwind's `md:` still
        // fires because breakpoints watch the VIEWPORT, not this column.
        'rsmm-section-header flex flex-wrap items-end justify-between gap-x-6 gap-y-3',
        compact ? 'gap-3 pb-2' : 'pb-4',
      )}
    >
      <div className="min-w-0 flex-1">
        <h2
          className={cn(
            'font-fraktur leading-none text-parchment',
            compact ? 'text-xl' : 'text-3xl',
          )}
        >
          {title}
        </h2>
        {subtitle ? (
          <p
            className={cn(
              'font-serif-italic text-ash',
              compact ? 'mt-1 text-sm' : 'mt-2 text-base',
            )}
          >
            {subtitle}
          </p>
        ) : null}
      </div>
      {right ? <div className="shrink-0">{right}</div> : null}
    </header>
  );
}

export function EmptyState({
  title,
  body,
  action,
}: {
  title: string;
  body: string;
  action?: ReactNode;
}) {
  return (
    <div className="grimoire-card mx-auto max-w-md p-10 text-center">
      <p className="font-fraktur text-2xl text-parchment">{title}</p>
      <p className="font-serif-italic mt-3 text-ash">{body}</p>
      {action ? <div className="mt-6 flex justify-center">{action}</div> : null}
    </div>
  );
}

export function Panel({ className, children, ...props }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div className={cn('grimoire-card p-6', className)} {...props}>
      {children}
    </div>
  );
}

export function InkSwitch({
  on,
  onClick,
  label,
}: {
  on: boolean;
  onClick: () => void;
  label: string;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={on}
      aria-label={label}
      onClick={onClick}
      className={cn(
        'relative inline-flex h-5 w-9 items-center border transition-colors duration-150 ease-grimoire',
        on ? 'border-crimson bg-crimson/40' : 'border-border bg-char',
      )}
    >
      <span
        className={cn(
          'block h-3 w-3 transition-transform duration-150 ease-grimoire',
          on ? 'translate-x-5 bg-parchment animate-ink-stamp' : 'translate-x-1 bg-smoke',
        )}
      />
    </button>
  );
}
