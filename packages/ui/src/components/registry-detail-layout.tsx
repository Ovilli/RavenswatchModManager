import type { ReactNode } from 'react';
import { RegistryModDetailHeader } from './registry-mod-detail-header';

/** Shared public listing detail frame. Apps provide route links, media and actions. */
export function RegistryDetailLayout({
  as: Root = 'main',
  className = '',
  name,
  summary,
  breadcrumb,
  labels,
  stats,
  media,
  navigation,
  sidebar,
  sidebarLabel,
  breadcrumbLabel = 'Breadcrumb',
  navigationLabel = 'On this page',
  children,
}: {
  as?: 'main' | 'div';
  className?: string;
  name: string;
  summary?: string | null;
  breadcrumb: ReactNode;
  labels?: ReactNode;
  stats: ReactNode;
  media: ReactNode;
  navigation?: ReactNode;
  sidebar: ReactNode;
  sidebarLabel: string;
  breadcrumbLabel?: string;
  navigationLabel?: string;
  children: ReactNode;
}) {
  return (
    <Root className={`mod-detail container ${className}`}>
      <nav aria-label={breadcrumbLabel} className="mod-breadcrumb">
        {breadcrumb}
      </nav>
      <RegistryModDetailHeader name={name} summary={summary} labels={labels} stats={stats} />
      {media}
      <div className="mod-body">
        {navigation ? (
          <nav className="mod-section-nav" aria-label={navigationLabel}>
            {navigation}
          </nav>
        ) : null}
        <RegistryDetailContentLayout sidebar={sidebar} sidebarLabel={sidebarLabel}>
          {children}
        </RegistryDetailContentLayout>
      </div>
    </Root>
  );
}

/** Shared reading column and sticky action rail used by both registry clients. */
export function RegistryDetailContentLayout({
  sidebar,
  sidebarLabel,
  children,
  className = '',
}: {
  sidebar: ReactNode;
  sidebarLabel: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <div className="registry-detail-content">
      <div className={`mod-content-grid ${className}`}>
        <aside className="mod-download-sidebar" aria-label={sidebarLabel}>
          {sidebar}
        </aside>
        <div className="mod-reading">{children}</div>
      </div>
    </div>
  );
}
