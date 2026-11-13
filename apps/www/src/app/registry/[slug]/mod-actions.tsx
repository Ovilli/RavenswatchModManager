'use client';
import type { ModVersion } from '@rsmm/schemas';
import { ArrowDownToLine, ExternalLink } from 'lucide-react';
import Link from 'next/link';
import { getApiUrl } from '../../../lib/api-url';
import { formatFileSize } from '../../../lib/mod-presentation';

export function ModActions({ slug, version }: { slug: string; version?: ModVersion }) {
  const downloadUrl = version
    ? `${getApiUrl().replace(/\/+$/, '')}/api/mods/${encodeURIComponent(slug)}/${encodeURIComponent(version.version)}/download`
    : null;
  return (
    <div className="mod-install">
      {version && downloadUrl ? (
        <>
          <a className="mod-download" href={downloadUrl}>
            <ArrowDownToLine size={20} aria-hidden />
            <span className="mod-download-copy">
              <span className="mod-download-label">Download mod</span>
              <span className="mod-download-meta">
                <span>Version {version.version}</span>
                <span aria-hidden>·</span>
                <span>{formatFileSize(version.sizeBytes)}</span>
              </span>
            </span>
          </a>
          <a className="mod-open-app" href={`rsmm://mods/${encodeURIComponent(slug)}`}>
            <ExternalLink size={17} aria-hidden /> Open in mod manager
          </a>
          <p className="mod-install-help">
            New to RSMM? <Link href="/download">Get the mod manager</Link>
          </p>
        </>
      ) : (
        <div className="mod-no-download">
          <strong>No download available yet</strong>
          <p>The author hasn’t published a downloadable version.</p>
        </div>
      )}
    </div>
  );
}
