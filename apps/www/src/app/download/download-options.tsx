'use client';

import { buttonVariants } from '@rsmm/ui';
import { ArrowDownToLine, ArrowUpRight, X } from 'lucide-react';
import { useEffect, useId, useRef, useState } from 'react';
import { type DownloadPlatform, detectDownloadPlatform } from '../../lib/download-platform';
import { LATEST_RELEASE_URL, type LatestRelease, formatBytes, pickAsset } from '../../lib/releases';
import { PlatformIcon } from './platform-icon';

const installGuideUrl = 'https://docs.rsmm.me/getting-started/install/';
const linuxPackages = [
  {
    name: 'AppImage',
    extension: '.AppImage',
    description: 'Portable · Linux & Steam Deck',
    note: 'Make the file executable before opening it.',
  },
  {
    name: 'Debian package',
    extension: '.deb',
    description: 'For Debian, Ubuntu and other apt-based distros',
    note: 'Install the .deb package with apt.',
  },
];

export function DownloadOptions({ release }: { release: LatestRelease }) {
  const [os, setOs] = useState<DownloadPlatform>('unknown');
  const [linuxOpen, setLinuxOpen] = useState(false);
  const dialog = useRef<HTMLDialogElement>(null);
  const dialogId = useId();
  const titleId = useId();
  const descriptionId = useId();

  useEffect(() => {
    setOs(detectDownloadPlatform(navigator));
    // Preserve platform links used by the mod page's installer fallback.
    function followPlatformLink() {
      if (window.location.hash === '#linux') {
        setOs('Linux');
        setLinuxOpen(true);
      } else if (window.location.hash === '#windows') {
        setOs('Windows');
      }
    }
    followPlatformLink();
    window.addEventListener('hashchange', followPlatformLink);
    return () => window.removeEventListener('hashchange', followPlatformLink);
  }, []);

  useEffect(() => {
    const node = dialog.current;
    if (!linuxOpen || !node) return;
    node.showModal();
    const overflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => {
      node.close();
      document.body.style.overflow = overflow;
    };
  }, [linuxOpen]);

  // Unsupported devices get an explicitly labelled Windows download, never a
  // promise of a macOS or mobile build. Linux is always one click away.
  const primaryPlatform = os === 'Linux' ? 'Linux' : 'Windows';
  const otherPlatform = primaryPlatform === 'Windows' ? 'Linux' : 'Windows';
  const windowsHref = release.windows ?? LATEST_RELEASE_URL;
  const primaryClassName = buttonVariants({
    size: 'lg',
    className: 'h-16 w-full justify-between gap-6 px-6 text-lg sm:h-20 sm:px-8 sm:text-xl',
  });
  const iconClassName =
    'inline-flex h-11 w-11 items-center justify-center rounded-md text-parchment/75 transition-colors hover:bg-parchment/5 hover:text-parchment focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background';
  const primaryContent = (
    <>
      <span>Download for {primaryPlatform}</span>
      <PlatformIcon platform={primaryPlatform} className="h-8 w-8 shrink-0" />
    </>
  );

  return (
    <section aria-label="Download options" className="mx-auto mt-10 max-w-sm">
      {primaryPlatform === 'Linux' ? (
        <button
          type="button"
          className={primaryClassName}
          aria-haspopup="dialog"
          aria-controls={dialogId}
          onClick={() => setLinuxOpen(true)}
        >
          {primaryContent}
        </button>
      ) : (
        <a href={windowsHref} className={primaryClassName}>
          {primaryContent}
        </a>
      )}

      <div className="mt-3 flex items-center justify-between gap-4">
        <span className="text-base text-parchment/75">Also available on:</span>
        {otherPlatform === 'Linux' ? (
          <button
            type="button"
            className={iconClassName}
            aria-label="Download for Linux"
            title="Linux & Steam Deck"
            aria-haspopup="dialog"
            aria-controls={dialogId}
            onClick={() => setLinuxOpen(true)}
          >
            <PlatformIcon platform="Linux" className="h-6 w-6" />
          </button>
        ) : (
          <a
            href={windowsHref}
            className={iconClassName}
            aria-label="Download for Windows"
            title="Windows 10 & 11"
          >
            <PlatformIcon platform="Windows" className="h-6 w-6" />
          </a>
        )}
      </div>

      <a
        className="mx-auto mt-5 flex w-fit items-center gap-1.5 rounded-sm text-sm text-parchment/75 underline-offset-4 hover:text-parchment hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        href={installGuideUrl}
        target="_blank"
        rel="noreferrer"
      >
        Installation guide
        <ArrowUpRight className="h-3.5 w-3.5" aria-hidden="true" />
      </a>

      <dialog
        ref={dialog}
        id={dialogId}
        aria-labelledby={titleId}
        aria-describedby={descriptionId}
        className="m-auto max-h-[calc(100dvh-2rem)] w-[calc(100%-2rem)] max-w-lg overflow-y-auto rounded-xl border border-border bg-card p-6 text-parchment backdrop:bg-black/70 sm:p-8"
        onCancel={(event) => {
          event.preventDefault();
          setLinuxOpen(false);
        }}
        onClick={(event) => {
          if (event.target !== event.currentTarget) return;
          const bounds = event.currentTarget.getBoundingClientRect();
          if (
            event.clientX < bounds.left ||
            event.clientX > bounds.right ||
            event.clientY < bounds.top ||
            event.clientY > bounds.bottom
          ) {
            setLinuxOpen(false);
          }
        }}
      >
        <div className="flex items-start justify-between gap-4">
          <div className="flex items-center gap-3">
            <PlatformIcon platform="Linux" className="h-7 w-7 shrink-0" />
            <h2 id={titleId} className="font-display text-3xl">
              Download for Linux
            </h2>
          </div>
          <button
            type="button"
            aria-label="Close Linux downloads"
            className="-mr-2 -mt-2 inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-md text-parchment/70 hover:bg-parchment/5 hover:text-parchment focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            onClick={() => setLinuxOpen(false)}
          >
            <X className="h-5 w-5" aria-hidden="true" />
          </button>
        </div>
        <p id={descriptionId} className="mt-3 text-base text-parchment/75">
          Choose a package for your Linux system.
        </p>

        <div className="mt-6 divide-y divide-border border-y border-border">
          {linuxPackages.map((pkg) => {
            const asset = pickAsset(release.assets, [pkg.extension]);
            return (
              <div key={pkg.extension} className="py-5">
                {asset ? (
                  <a
                    href={asset.url}
                    className="group flex items-center justify-between gap-4 rounded-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-4 focus-visible:ring-offset-card"
                  >
                    <span className="min-w-0">
                      <span className="block text-lg font-semibold group-hover:underline group-hover:underline-offset-4">
                        {pkg.name}
                      </span>
                      <span className="mt-1 block text-sm text-parchment/75">
                        {pkg.description}
                      </span>
                    </span>
                    <span className="flex shrink-0 items-center gap-3 text-sm text-parchment/75">
                      {asset.size > 0 ? formatBytes(asset.size) : null}
                      <ArrowDownToLine className="h-5 w-5 text-parchment" aria-hidden="true" />
                    </span>
                  </a>
                ) : (
                  <div>
                    <p className="text-lg font-semibold">{pkg.name}</p>
                    <p className="mt-1 text-sm text-parchment/75">
                      Unavailable in this release.{' '}
                      <a href={LATEST_RELEASE_URL} className="underline underline-offset-4">
                        Check GitHub releases
                      </a>
                    </p>
                  </div>
                )}
                {asset ? <p className="mt-2 text-sm text-parchment/65">{pkg.note}</p> : null}
              </div>
            );
          })}
        </div>

        <div className="mt-5 flex flex-wrap items-center justify-between gap-x-4 gap-y-3 text-sm">
          <p className="text-parchment/65">Requires WebKitGTK 4.1.</p>
          <a
            href={installGuideUrl}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1 underline underline-offset-4 hover:text-gilt"
          >
            Installation guide
            <ArrowUpRight className="h-3.5 w-3.5" aria-hidden="true" />
          </a>
        </div>
      </dialog>
    </section>
  );
}
