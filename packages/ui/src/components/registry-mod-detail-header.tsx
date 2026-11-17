import type { ReactNode } from 'react';

/** The web registry's canonical title, summary and social proof treatment. */
export function RegistryModDetailHeader({
  name,
  summary,
  labels,
  stats,
  action,
  className = '',
}: {
  name: string;
  summary?: string | null;
  labels?: ReactNode;
  stats?: ReactNode;
  action?: ReactNode;
  className?: string;
}) {
  return (
    <header className={`mod-heading ${className}`}>
      {labels}
      <div className="mod-heading-row">
        <div className="mod-heading-copy">
          <h1>{name}</h1>
          {summary?.trim() ? <p className="mod-summary">{summary}</p> : null}
        </div>
        {action ? <div className="mod-heading-action">{action}</div> : null}
      </div>
      {stats ? <div className="mod-social-proof">{stats}</div> : null}
    </header>
  );
}
