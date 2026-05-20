import { cn } from '@rsmm/ui';
import type { ButtonHTMLAttributes, HTMLAttributes, ReactNode } from 'react';

export function Fleuron({
  className,
}: {
  className?: string;
}) {
  return <div className={cn('rule-fleuron text-[0.9rem]', className)} />;
}

export function Crest({
  monogram = 'R',
  size = 'md',
  className,
}: {
  monogram?: string;
  size?: 'sm' | 'md' | 'lg';
  className?: string;
}) {
  const sizeClass =
    size === 'sm' ? 'h-10 w-10' : size === 'lg' ? 'h-14 w-14' : 'h-12 w-12';
  return (
    <span className={cn('brand-crest', sizeClass, className)} aria-hidden>
      <span className="font-fraktur text-2xl leading-none">{monogram}</span>
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
  return (
    <div className={cn('cover-placeholder aspect-[16/9] w-full', className)}>{caption}</div>
  );
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
}: {
  src?: string | null;
  alt: string;
  caption?: string;
  className?: string;
}) {
  if (!src) return <CoverPlaceholder caption={caption} className={className} />;
  return (
    <div
      className={cn(
        'relative aspect-[16/9] w-full overflow-hidden border border-border bg-pitch',
        className,
      )}
    >
      <img
        src={src}
        alt={alt}
        loading="lazy"
        className="h-full w-full object-cover"
      />
    </div>
  );
}

interface MdBlock {
  kind: 'h1' | 'h2' | 'h3' | 'p' | 'ul' | 'quote' | 'code';
  text?: string;
  items?: string[];
}

function parseMarkdownBlocks(src: string): MdBlock[] {
  const out: MdBlock[] = [];
  const lines = src.replace(/\r\n/g, '\n').split('\n');
  let i = 0;
  while (i < lines.length) {
    const line = lines[i] ?? '';
    if (line.trim() === '') { i++; continue; }
    if (line.startsWith('```')) {
      const buf: string[] = [];
      i++;
      while (i < lines.length && !(lines[i] ?? '').startsWith('```')) {
        buf.push(lines[i] ?? '');
        i++;
      }
      i++;
      out.push({ kind: 'code', text: buf.join('\n') });
      continue;
    }
    if (line.startsWith('### ')) { out.push({ kind: 'h3', text: line.slice(4) }); i++; continue; }
    if (line.startsWith('## ')) { out.push({ kind: 'h2', text: line.slice(3) }); i++; continue; }
    if (line.startsWith('# ')) { out.push({ kind: 'h1', text: line.slice(2) }); i++; continue; }
    if (line.startsWith('> ')) {
      const buf: string[] = [line.slice(2)];
      i++;
      while (i < lines.length && (lines[i] ?? '').startsWith('> ')) {
        buf.push((lines[i] ?? '').slice(2));
        i++;
      }
      out.push({ kind: 'quote', text: buf.join(' ') });
      continue;
    }
    if (/^(-|\d+\.)\s/.test(line)) {
      const items: string[] = [];
      while (i < lines.length && /^(-|\d+\.)\s/.test(lines[i] ?? '')) {
        items.push((lines[i] ?? '').replace(/^(-|\d+\.)\s/, ''));
        i++;
      }
      out.push({ kind: 'ul', items });
      continue;
    }
    const buf: string[] = [line];
    i++;
    while (i < lines.length) {
      const nxt = lines[i] ?? '';
      if (nxt.trim() === '' || /^(#{1,3}\s|>\s|-\s|\d+\.\s|```)/.test(nxt)) break;
      buf.push(nxt);
      i++;
    }
    out.push({ kind: 'p', text: buf.join(' ') });
  }
  return out;
}

function renderInline(src: string, keyPrefix: string): ReactNode[] {
  const nodes: ReactNode[] = [];
  const pattern = /(`[^`]+`|\*\*[^*]+\*\*|\*[^*]+\*|\[[^\]]+\]\([^)]+\))/g;
  let lastIdx = 0;
  let match: RegExpExecArray | null;
  let n = 0;
  match = pattern.exec(src);
  while (match !== null) {
    if (match.index > lastIdx) nodes.push(src.slice(lastIdx, match.index));
    const tok = match[0];
    const key = `${keyPrefix}-${n++}`;
    if (tok.startsWith('`')) {
      nodes.push(
        <code key={key} className="font-mono border border-border bg-char/40 px-1 text-parchment">
          {tok.slice(1, -1)}
        </code>,
      );
    } else if (tok.startsWith('**')) {
      nodes.push(<strong key={key} className="text-parchment">{tok.slice(2, -2)}</strong>);
    } else if (tok.startsWith('*')) {
      nodes.push(<em key={key}>{tok.slice(1, -1)}</em>);
    } else {
      const m = /^\[([^\]]+)\]\(([^)]+)\)$/.exec(tok);
      if (m) {
        nodes.push(
          <a key={key} href={m[2]} target="_blank" rel="noreferrer noopener" className="text-gilt hover:underline">
            {m[1]}
          </a>,
        );
      }
    }
    lastIdx = match.index + tok.length;
    match = pattern.exec(src);
  }
  if (lastIdx < src.length) nodes.push(src.slice(lastIdx));
  return nodes;
}

/**
 * Minimal Markdown renderer for mod store-page copy. Handles
 * headings, paragraphs, lists, blockquotes, fenced code, plus
 * inline bold/italic/code/links. Intentionally tiny — not a CommonMark
 * implementation; we only render trusted mod-authored copy.
 */
export function Markdown({ source, className }: { source: string; className?: string }) {
  const blocks = parseMarkdownBlocks(source);
  return (
    <div className={cn('space-y-4 text-parchment/90', className)}>
      {blocks.map((b, idx) => {
        const k = `md-${idx}`;
        switch (b.kind) {
          case 'h1':
            return (
              <h1 key={k} className="font-fraktur text-3xl text-parchment">
                {renderInline(b.text ?? '', k)}
              </h1>
            );
          case 'h2':
            return (
              <h2 key={k} className="font-fraktur text-2xl text-parchment">
                {renderInline(b.text ?? '', k)}
              </h2>
            );
          case 'h3':
            return (
              <h3 key={k} className="font-fraktur text-xl text-parchment">
                {renderInline(b.text ?? '', k)}
              </h3>
            );
          case 'ul':
            return (
              <ul key={k} className="font-serif-italic list-disc space-y-1 pl-6">
                {(b.items ?? []).map((it) => (
                  <li key={`${k}-${it}`}>{renderInline(it, `${k}-${it}`)}</li>
                ))}
              </ul>
            );
          case 'quote':
            return (
              <blockquote
                key={k}
                className="font-serif-italic border-l-2 border-gilt/60 pl-4 text-ash"
              >
                {renderInline(b.text ?? '', k)}
              </blockquote>
            );
          case 'code':
            return (
              <pre
                key={k}
                className="font-mono overflow-x-auto border border-border bg-pitch/60 p-3 text-ash"
              >
                {b.text}
              </pre>
            );
          default:
            return (
              <p key={k} className="font-serif-italic leading-relaxed">
                {renderInline(b.text ?? '', k)}
              </p>
            );
        }
      })}
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

export function SectionHeader({
  title,
  subtitle,
  right,
}: {
  title: string;
  subtitle?: string;
  right?: ReactNode;
}) {
  return (
    <header className="flex items-end justify-between gap-6 pb-4">
      <div>
        <h2 className="font-fraktur text-3xl text-parchment leading-none">{title}</h2>
        {subtitle ? (
          <p className="font-serif-italic mt-2 text-ash text-base">{subtitle}</p>
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

export function Panel({
  className,
  children,
  ...props
}: HTMLAttributes<HTMLDivElement>) {
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
        on
          ? 'border-crimson bg-crimson/40'
          : 'border-border bg-char',
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
