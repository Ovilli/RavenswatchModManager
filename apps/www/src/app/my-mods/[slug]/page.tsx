'use client';

import { ApiError } from '@rsmm/api-client';
import { type ModCategory, type ModPatch, hasPrivateOnlyTag, modPatchSchema } from '@rsmm/schemas';
import { Badge, Button, Input, ProgressBar, Spinner, buttonVariants } from '@rsmm/ui';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  AlertTriangle,
  BarChart3,
  Eye,
  Loader2,
  Package,
  Pencil,
  Trash2,
  Upload,
  Users,
} from 'lucide-react';
import Link from 'next/link';
import { useParams, useRouter } from 'next/navigation';
import { useNavigationGuard } from 'nextjs-nav-guard';
import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../../../lib/api';
import { useSession } from '../../../lib/auth-client';
import { type ListingDraft, listingChanges, readListingDraft } from '../../../lib/listing-draft';
import { fmtBytes, hexToBase64, putFile, sha256Hex } from '../../../lib/upload';
import { useScreenshotGallery } from '../../../lib/use-screenshot-gallery';
import { FileDrop } from '../../components/file-drop';
import { MDEditor } from '../../components/md-editor';
import { ModStats } from '../../components/mod-stats';
import { ModTeam } from '../../components/mod-team';
import { ListingLeaveDialog, ListingSaveBar } from './listing-save-bar';
import { ScreenshotEditor } from './screenshot-editor';
import './editor.css';

const CATEGORIES: ModCategory[] = [
  'gameplay',
  'balance',
  'cosmetic',
  'qol',
  'audio',
  'difficulty',
  'speedrun',
  'utility',
];

const SEMVER_RE = /^\d+\.\d+\.\d+(?:[-+][\w.]+)?$/;

/** Anchor navigation for the continuous editor, with shareable section links. */
const SECTIONS = [
  { id: 'listing', label: 'Listing', icon: Pencil },
  { id: 'versions', label: 'Versions', icon: Package },
  { id: 'analytics', label: 'Analytics', icon: BarChart3 },
  { id: 'team', label: 'Team', icon: Users },
  { id: 'danger', label: 'Danger zone', icon: AlertTriangle },
] as const;
type SectionId = (typeof SECTIONS)[number]['id'];

function SectionNav({
  active,
  navRef,
  onSelect,
  versionCount,
  hasInReview,
}: {
  active: SectionId;
  navRef: React.RefObject<HTMLElement | null>;
  onSelect: (id: SectionId) => void;
  versionCount: number;
  hasInReview: boolean;
}) {
  return (
    <nav
      ref={navRef}
      aria-label="Mod sections"
      className="sticky top-[var(--site-header-height,61px)] z-30 flex h-16 gap-1 overflow-x-auto bg-background p-2 md:top-[calc(var(--site-header-height,61px)+24px)] md:h-auto md:flex-col md:self-start md:bg-transparent"
    >
      {SECTIONS.map((s) => {
        const isActive = active === s.id;
        const Icon = s.icon;
        const tone =
          s.id === 'danger'
            ? isActive
              ? 'bg-destructive/10 font-medium text-destructive'
              : 'text-muted-foreground hover:bg-destructive/10 hover:text-destructive'
            : isActive
              ? 'bg-secondary/70 font-medium text-foreground'
              : 'text-muted-foreground hover:bg-secondary/40 hover:text-foreground';
        return (
          <a
            key={s.id}
            href={`#${s.id}`}
            onClick={(event) => {
              if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
              event.preventDefault();
              onSelect(s.id);
            }}
            aria-current={isActive ? 'location' : undefined}
            className={`flex shrink-0 items-center gap-2 rounded-md px-3 py-2 text-sm transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring md:w-full ${tone}`}
          >
            <Icon className="h-4 w-4 shrink-0" />
            {s.label}
            {s.id === 'versions' ? (
              <span className="ml-auto flex items-center gap-1.5 pl-2">
                {hasInReview ? (
                  <span
                    className="h-1.5 w-1.5 animate-pulse rounded-full bg-amber-500"
                    title="A version is in review"
                  />
                ) : null}
                <span className="rounded-full bg-secondary px-1.5 text-[10px] leading-4 text-muted-foreground">
                  {versionCount}
                </span>
              </span>
            ) : null}
          </a>
        );
      })}
    </nav>
  );
}

function Label({
  htmlFor,
  children,
}: {
  htmlFor?: string;
  children: React.ReactNode;
}) {
  return (
    <label htmlFor={htmlFor} className="text-sm font-medium leading-none">
      {children}
    </label>
  );
}

function describeApiError(err: unknown): string {
  if (err instanceof ApiError) {
    const body = err.body as { error?: string } | null;
    if (body?.error) return body.error;
    return `HTTP ${err.status}`;
  }
  return err instanceof Error ? err.message : String(err);
}

/** Live malware-scan status for one version. Polls while queued/pending so the
 *  author sees their place in the queue and the eventual verdict. Flagged
 *  versions stay listed for the author (file removed, download blocked). */
function ScanBadge({ versionId }: { versionId: string }) {
  const qc = useQueryClient();
  const q = useQuery({
    queryKey: ['scan-status', versionId],
    queryFn: () => api.mods.scanStatus(versionId),
    refetchInterval: (query) => {
      const s = query.state.data?.status;
      return s === 'queued' || s === 'pending' ? 5000 : false;
    },
  });
  const d = q.data;
  // When a watched scan settles, refetch the mod detail so the version row's
  // "in review" note (rendered from the cached detail) clears without a reload.
  const prevStatus = useRef<string | undefined>(undefined);
  useEffect(() => {
    const s = d?.status;
    const wasInFlight = prevStatus.current === 'queued' || prevStatus.current === 'pending';
    if (s && s !== prevStatus.current && wasInFlight) {
      qc.invalidateQueries({ queryKey: ['my-mod'] });
    }
    prevStatus.current = s;
  }, [d?.status, qc]);
  if (!d) return null;
  const label =
    d.status === 'queued'
      ? d.position
        ? `Queued · #${d.position}${d.etaSeconds ? ` · ~${Math.ceil(d.etaSeconds / 60)}m` : ''}`
        : 'Queued'
      : d.status === 'pending'
        ? 'Scanning…'
        : d.status === 'clean'
          ? 'Scanned ✓'
          : d.status === 'skipped'
            ? 'Scan off'
            : d.status === 'error'
              ? 'Scan error — retrying'
              : d.status === 'flagged'
                ? 'Flagged ✕'
                : d.status;
  return (
    <Badge
      variant={
        d.status === 'clean' ? 'secondary' : d.status === 'flagged' ? 'destructive' : 'outline'
      }
    >
      {label}
    </Badge>
  );
}

export default function ManageModPage() {
  const { slug } = useParams<{ slug: string }>();
  return <ManageModEditor key={slug} slug={slug} />;
}

function EditableModTitle({
  value,
  fallback,
  onChange,
}: {
  value: string;
  fallback: string;
  onChange: (value: string) => void;
}) {
  const [editing, setEditing] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const original = useRef(value);
  const restoreFocus = useRef(false);
  const title = value.trim() || fallback;

  useEffect(() => {
    if (editing) {
      input.current?.focus();
      input.current?.select();
    } else if (restoreFocus.current) {
      trigger.current?.focus();
      restoreFocus.current = false;
    }
  }, [editing]);

  return (
    <h1 aria-label={title} className="min-w-0 tracking-tight">
      {editing ? (
        <Input
          ref={input}
          aria-label="Display name"
          className="mod-name-input"
          value={value}
          maxLength={128}
          onChange={(event) => onChange(event.target.value)}
          onBlur={() => {
            onChange(value.trim() || original.current || fallback);
            setEditing(false);
          }}
          onKeyDown={(event) => {
            if (event.nativeEvent.isComposing) return;
            if (event.key === 'Escape') {
              event.preventDefault();
              onChange(original.current);
              restoreFocus.current = true;
              setEditing(false);
            } else if (event.key === 'Enter') {
              event.preventDefault();
              restoreFocus.current = true;
              event.currentTarget.blur();
            }
          }}
        />
      ) : (
        <button
          ref={trigger}
          type="button"
          aria-label={`Edit mod name: ${title}`}
          onClick={() => {
            original.current = value;
            setEditing(true);
          }}
          className="flex min-h-11 w-full items-center gap-3 rounded-md text-left hover:bg-secondary/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          <span className="min-w-0 break-words">{title}</span>
          <Pencil className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden="true" />
        </button>
      )}
    </h1>
  );
}

function ManageModEditor({ slug }: { slug: string }) {
  const router = useRouter();
  const qc = useQueryClient();
  const { data: session, isPending: sessionLoading } = useSession();

  const detail = useQuery({
    queryKey: ['my-mod', slug],
    queryFn: () => api.mods.get(slug),
    enabled: !!slug,
  });

  // Form state for metadata edit
  const [name, setName] = useState('');
  const [author, setAuthor] = useState('');
  const [summary, setSummary] = useState('');
  const [description, setDescription] = useState<string | undefined>('');
  const [category, setCategory] = useState<ModCategory | null>(null);
  const [tags, setTags] = useState('');
  const [privateOnly, setPrivateOnly] = useState(false);
  const [license, setLicense] = useState('');
  const [repoUrl, setRepoUrl] = useState('');
  const [homepageUrl, setHomepageUrl] = useState('');
  const [savedListing, setSavedListing] = useState<ListingDraft | null>(null);
  const [validationError, setValidationError] = useState<string | null>(null);
  const saveInFlight = useRef(false);
  const allowLeave = useRef(false);
  const [nsfw, setNsfw] = useState(false);
  const gallery = useScreenshotGallery(slug, detail.data?.mod);
  const { screenshots, coverUrl } = gallery;
  const [videos, setVideos] = useState<string[]>([]);
  const [videoInput, setVideoInput] = useState('');
  const [section, setSection] = useState<SectionId>('listing');
  const sectionNav = useRef<HTMLElement>(null);
  const sectionContent = useRef<HTMLDivElement>(null);
  const requestedSection = useRef<SectionId | null>(null);
  const editorReady =
    !!session && !!detail.data && !sessionLoading && !detail.isLoading && !detail.isError;

  const selectSection = useCallback((id: SectionId) => {
    const target = document.getElementById(id);
    if (!target) return;
    requestedSection.current = id;
    if (window.location.hash !== `#${id}`) window.history.pushState(null, '', `#${id}`);
    setSection(id);
    target.focus({ preventScroll: true });
    target.scrollIntoView({
      block: 'start',
      behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches
        ? 'instant'
        : 'smooth',
    });
  }, []);

  useEffect(() => {
    if (!editorReady || !sectionContent.current) return;
    const content = sectionContent.current;
    const sections = SECTIONS.map(({ id }) => document.getElementById(id)).filter(
      (node): node is HTMLElement => node !== null,
    );
    const first = sections[0];
    if (!first) return;
    const previousRestoration = window.history.scrollRestoration;
    window.history.scrollRestoration = 'manual';
    let frame = 0;
    let navigationFrame = 0;
    const updateActive = () => {
      frame = 0;
      const offset = Number.parseFloat(getComputedStyle(first).scrollMarginTop) + 8;
      const atBottom =
        window.scrollY + window.innerHeight >= document.documentElement.scrollHeight - 2;
      // Keep a clicked section selected during its scroll, including short sections
      // near the footer that cannot reach the top. Manual scrolling resumes tracking.
      const current = requestedSection.current
        ? sections.find((node) => node.id === requestedSection.current)
        : atBottom
          ? sections[sections.length - 1]
          : sections.reduce(
              (active, node) => (node.getBoundingClientRect().top <= offset ? node : active),
              first,
            );
      if (!current) return;
      const id = current.id as SectionId;
      setSection(id);
      if (window.location.hash !== `#${id}`) window.history.replaceState(null, '', `#${id}`);
    };
    const scheduleUpdate = () => {
      if (!frame) frame = requestAnimationFrame(updateActive);
    };
    const followHash = () => {
      const hash = window.location.hash.slice(1);
      const id = hash === 'gallery' ? 'listing' : hash;
      const target = sections.find((node) => node.id === id);
      if (target) {
        requestedSection.current = id as SectionId;
        setSection(id as SectionId);
        // Run after history traversal finishes restoring the document's scroll.
        cancelAnimationFrame(navigationFrame);
        navigationFrame = requestAnimationFrame(() => {
          target.focus({ preventScroll: true });
          target.scrollIntoView({ block: 'start', behavior: 'instant' });
          scheduleUpdate();
        });
      }
      scheduleUpdate();
    };
    const resumeTracking = () => {
      requestedSection.current = null;
    };
    const onScrollKey = (event: KeyboardEvent) => {
      if (['ArrowUp', 'ArrowDown', 'PageUp', 'PageDown', 'Home', 'End', ' '].includes(event.key))
        resumeTracking();
    };
    followHash();
    window.addEventListener('scroll', scheduleUpdate, { passive: true });
    window.addEventListener('resize', scheduleUpdate);
    window.addEventListener('hashchange', followHash);
    window.addEventListener('popstate', followHash);
    window.addEventListener('wheel', resumeTracking, { passive: true });
    window.addEventListener('touchstart', resumeTracking, { passive: true });
    window.addEventListener('pointerdown', resumeTracking, { passive: true });
    window.addEventListener('keydown', onScrollKey);
    // Keep the active link correct as uploads, analytics, or form errors change section heights.
    const observer = new ResizeObserver(scheduleUpdate);
    observer.observe(content);
    return () => {
      cancelAnimationFrame(frame);
      cancelAnimationFrame(navigationFrame);
      observer.disconnect();
      window.history.scrollRestoration = previousRestoration;
      window.removeEventListener('scroll', scheduleUpdate);
      window.removeEventListener('resize', scheduleUpdate);
      window.removeEventListener('hashchange', followHash);
      window.removeEventListener('popstate', followHash);
      window.removeEventListener('wheel', resumeTracking);
      window.removeEventListener('touchstart', resumeTracking);
      window.removeEventListener('pointerdown', resumeTracking);
      window.removeEventListener('keydown', onScrollKey);
    };
  }, [editorReady]);

  useEffect(() => {
    const nav = sectionNav.current;
    const link = nav?.querySelector<HTMLAnchorElement>(`a[href="#${section}"]`);
    if (!nav || !link) return;
    if (link.offsetLeft < nav.scrollLeft) nav.scrollLeft = link.offsetLeft;
    else if (link.offsetLeft + link.offsetWidth > nav.scrollLeft + nav.clientWidth)
      nav.scrollLeft = link.offsetLeft + link.offsetWidth - nav.clientWidth;
  }, [section]);

  const restoreListing = useCallback((draft: ListingDraft) => {
    setName(draft.name);
    setAuthor(draft.author);
    setSummary(draft.summary);
    setDescription(draft.description);
    setCategory(draft.category);
    setTags(draft.tags);
    setPrivateOnly(draft.privateOnly);
    setLicense(draft.license);
    setRepoUrl(draft.repoUrl);
    setHomepageUrl(draft.homepageUrl);
    setNsfw(draft.nsfw);
    setVideos(draft.videos);
  }, []);

  // Hydrate once. Refetching versions or team data must not overwrite draft edits.
  const metadataHydrated = useRef(false);
  useEffect(() => {
    if (!detail.data || metadataHydrated.current) return;
    metadataHydrated.current = true;
    const initial = readListingDraft(detail.data);
    restoreListing(initial);
    setSavedListing(initial);
  }, [detail.data, restoreListing]);

  const listing: ListingDraft = {
    name,
    author,
    summary,
    description: description ?? '',
    category,
    tags,
    privateOnly,
    license,
    repoUrl,
    homepageUrl,
    nsfw,
    videos,
    photos: screenshots,
  };
  const changes = savedListing ? listingChanges(savedListing, listing) : {};
  const dirty = Object.keys(changes).length > 0;

  const saveListing = useMutation({
    mutationFn: async ({ patch }: { patch: ModPatch; snapshot: ListingDraft }) => {
      await api.mods.patch(slug, patch);
    },
    onSuccess: (_result, { snapshot }) => {
      // Only mark the submitted snapshot saved. Edits made while the request
      // was running remain dirty, including new photo uploads or ordering.
      const savedPrivateOnly = snapshot.privateOnly || hasPrivateOnlyTag(snapshot.tags.split(','));
      setSavedListing({ ...snapshot, privateOnly: savedPrivateOnly });
      if (savedPrivateOnly) setPrivateOnly(true);
      qc.invalidateQueries({ queryKey: ['my-mod', slug] });
      qc.invalidateQueries({ queryKey: ['me', 'mods'] });
      qc.invalidateQueries({ queryKey: ['mods', 'detail', slug] });
      qc.invalidateQueries({ queryKey: ['registry'] });
      if (document.activeElement?.closest('[aria-label="Listing changes"]'))
        document.getElementById(section)?.focus({ preventScroll: true });
    },
    onSettled: () => {
      saveInFlight.current = false;
    },
  });

  const hasUnsavedChanges = dirty || gallery.isUploading || saveListing.isPending;
  const navigationGuard = useNavigationGuard({
    enabled: ({ to, type }) => {
      if (allowLeave.current || !hasUnsavedChanges) return false;
      if (type === 'beforeunload' || type === 'refresh') return true;
      const target = new URL(to, window.location.href);
      // Section anchors are navigation within the same draft, not leaving it.
      // During popstate the address bar already contains the destination.
      // Compare with this editor's route, not window.location.pathname.
      return target.pathname !== `/my-mods/${encodeURIComponent(slug)}`;
    },
  });

  function saveChanges() {
    if (!dirty || gallery.isUploading || saveInFlight.current) return;
    const parsed = modPatchSchema.safeParse(changes);
    if (!parsed.success) {
      const issue = parsed.error.issues[0];
      const labels: Record<string, string> = {
        name: 'mod name',
        author: 'author credit',
        repoUrl: 'repository URL',
        homepageUrl: 'homepage URL',
        screenshots: 'photos',
        imageUrl: 'cover photo',
        nsfw: 'mature content setting',
      };
      const field = String(issue?.path[0] ?? 'the listing');
      setValidationError(`Check ${labels[field] ?? field}: ${issue?.message ?? 'Invalid value'}`);
      return;
    }
    setValidationError(null);
    saveInFlight.current = true;
    saveListing.mutate({ patch: parsed.data, snapshot: listing });
  }

  function discardChanges() {
    if (!savedListing || saveInFlight.current) return;
    restoreListing(savedListing);
    gallery.reset(savedListing.photos);
    setVideoInput('');
    setValidationError(null);
    saveListing.reset();
    document.getElementById(section)?.focus({ preventScroll: true });
  }

  const contextualSaveBar = (
    <>
      <ListingLeaveDialog
        active={navigationGuard.active}
        saving={saveListing.isPending}
        onStay={navigationGuard.reject}
        onLeave={navigationGuard.accept}
      />
      {hasUnsavedChanges ? (
        <ListingSaveBar
          saving={saveListing.isPending}
          uploading={gallery.isUploading}
          error={
            validationError || (saveListing.isError ? describeApiError(saveListing.error) : null)
          }
          onSave={saveChanges}
          onDiscard={discardChanges}
        />
      ) : null}
    </>
  );

  function addVideo() {
    const trimmed = videoInput.trim();
    if (!trimmed || videos.length >= 8) return;
    setVideos([...videos, trimmed]);
    setVideoInput('');
  }

  function removeVideo(idx: number) {
    setVideos(videos.filter((_, i) => i !== idx));
  }

  // New version section
  const [newVersion, setNewVersion] = useState('');
  const [newZip, setNewZip] = useState<File | null>(null);
  const [changelog, setChangelog] = useState<string | undefined>('');
  const [zipProgress, setZipProgress] = useState<{ loaded: number; total: number } | null>(null);
  const newVersionMut = useMutation({
    mutationFn: async () => {
      if (!newZip) throw new Error('no zip selected');
      if (!SEMVER_RE.test(newVersion)) throw new Error('version must be semver x.y.z');
      const sha = await sha256Hex(newZip);
      const mod = detail.data?.mod;
      if (!mod) throw new Error('mod not loaded');
      const manifest = {
        id: slug,
        name: mod.name,
        version: newVersion,
        author: mod.author ?? undefined,
        summary: mod.summary ?? undefined,
        description: savedListing?.description.trim() || undefined,
        license: mod.license ?? undefined,
        tags: mod.tags,
      };
      const presigned = await api.mods.createVersion(slug, {
        version: newVersion,
        sha256: sha,
        sizeBytes: newZip.size,
        manifest,
        changelog: changelog?.trim() || undefined,
      });
      setZipProgress({ loaded: 0, total: newZip.size });
      try {
        await putFile(presigned.uploadUrl, newZip, {
          headers: {
            'Content-Type': 'application/zip',
            'x-amz-checksum-sha256': hexToBase64(sha),
          },
          what: 'mod archive upload',
          onProgress: (loaded, total) => setZipProgress({ loaded, total }),
          confirmUpload: () => api.mods.scanVersion(presigned.versionId),
        });
      } finally {
        setZipProgress(null);
      }
    },
    onSuccess: () => {
      setNewZip(null);
      setNewVersion('');
      setChangelog('');
      qc.invalidateQueries({ queryKey: ['my-mod', slug] });
    },
  });

  const removeVersion = useMutation({
    mutationFn: (versionId: string) => api.mods.removeVersion(versionId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['my-mod', slug] });
      qc.invalidateQueries({ queryKey: ['me', 'mods'] });
    },
  });

  const remove = useMutation({
    mutationFn: () => api.mods.remove(slug),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['me', 'mods'] });
      allowLeave.current = true;
      router.push('/my-mods');
    },
  });

  if (sessionLoading || detail.isLoading) {
    return (
      <main className="container mx-auto px-6 py-16">
        <div className="flex items-center gap-2 text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" /> Loading…
        </div>
      </main>
    );
  }

  if (!session) {
    return (
      <main className="container mx-auto px-6 py-16">
        <div className="mx-auto max-w-md text-center">
          <h1 className="text-3xl font-bold tracking-tight">Sign in required</h1>
          <Link
            href={{ pathname: '/auth/signin' }}
            className="mt-6 inline-flex h-10 items-center justify-center rounded-md bg-primary px-6 text-sm font-medium text-primary-foreground hover:bg-primary/90"
          >
            Sign in
          </Link>
        </div>
      </main>
    );
  }

  if (detail.isError || !detail.data) {
    return (
      <main className="container mx-auto px-6 py-16">
        <p className="text-sm text-destructive">
          Cannot load mod {slug} ({String(detail.error)})
        </p>
      </main>
    );
  }

  const mod = detail.data.mod;
  const versions = detail.data.versions;

  const hasInReview = versions.some(
    (v) => v.scanStatus && v.scanStatus !== 'clean' && v.scanStatus !== 'skipped',
  );

  return (
    <main className="mod-editor container mx-auto space-y-8 px-6 py-12">
      {contextualSaveBar}
      <div className="gap-8 [--editor-scroll-offset:calc(var(--site-header-height,61px)+88px)] md:grid md:grid-cols-[200px_minmax(0,1fr)] md:[--editor-scroll-offset:calc(var(--site-header-height,61px)+24px)]">
        <SectionNav
          active={section}
          navRef={sectionNav}
          onSelect={selectSection}
          versionCount={versions.length}
          hasInReview={hasInReview}
        />
        <div ref={sectionContent} className="mod-editor-sections mt-6 min-w-0 space-y-8 md:mt-0">
          <section
            id="listing"
            aria-label="Listing"
            tabIndex={-1}
            className="scroll-mt-[var(--editor-scroll-offset)] space-y-8 focus:outline-none"
          >
            <header className="grid items-start gap-4 sm:grid-cols-[minmax(0,1fr)_auto]">
              <div className="flex min-w-0 items-start gap-4">
                {coverUrl ? (
                  <img
                    src={coverUrl}
                    alt=""
                    className="mt-1 hidden h-12 w-12 shrink-0 rounded-md border border-border/40 object-cover sm:block"
                  />
                ) : null}
                <div className="min-w-0 flex-1">
                  <p className="font-data text-xs text-muted-foreground">{mod.slug}</p>
                  <EditableModTitle
                    value={name}
                    fallback={mod.name}
                    onChange={(value) => {
                      setName(value);
                      setValidationError(null);
                    }}
                  />
                </div>
              </div>
              <Link
                href={`/registry/${mod.slug}` as never}
                className={buttonVariants({ variant: 'outline', className: 'justify-self-start' })}
              >
                <Eye className="h-4 w-4" aria-hidden="true" /> View public page
              </Link>
            </header>

            {mod.takedownStatus && mod.takedownStatus !== 'active' ? (
              <div className="flex items-start gap-3 rounded-md border border-destructive/40 bg-destructive/10 p-4">
                <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-destructive" />
                <div className="text-sm">
                  <p className="font-semibold text-destructive">
                    This mod has been {mod.takedownStatus === 'removed' ? 'removed' : 'hidden'} by a
                    moderator.
                  </p>
                  <p className="mt-1 text-muted-foreground">
                    It is not visible in the public registry or downloadable.
                    {mod.takedownReason ? ` Reason: ${mod.takedownReason}.` : ''} If you believe
                    this was a mistake,{' '}
                    <Link href="/contact" className="underline underline-offset-2">
                      contact the moderators
                    </Link>
                    .
                  </p>
                </div>
              </div>
            ) : null}

            {/* ─── Metadata edit ─── */}
            <section className="space-y-4">
              <div className="grid gap-4 sm:grid-cols-2">
                <div className="space-y-2 sm:col-span-2">
                  <Label htmlFor="summary">Summary</Label>
                  <Input
                    id="summary"
                    value={summary}
                    onChange={(e) => setSummary(e.target.value)}
                    maxLength={512}
                  />
                </div>
                <div className="space-y-2 sm:col-span-2">
                  <Label htmlFor="author">Author</Label>
                  <Input
                    id="author"
                    value={author}
                    onChange={(e) => setAuthor(e.target.value)}
                    maxLength={128}
                    aria-describedby="author-hint"
                  />
                  <p id="author-hint" className="text-xs text-muted-foreground">
                    The name credited on the public mod page.
                  </p>
                </div>
                <div className="space-y-2 sm:col-span-2">
                  <Label>Description (Markdown)</Label>
                  <div data-color-mode="dark" className="md-editor-themed min-h-80">
                    <MDEditor value={description} onChange={setDescription} height={320} />
                  </div>
                </div>
                <div className="space-y-2">
                  <Label htmlFor="category">Category</Label>
                  <select
                    id="category"
                    value={category ?? ''}
                    onChange={(e) => setCategory((e.target.value || null) as ModCategory | null)}
                    className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm"
                  >
                    <option value="">No category</option>
                    {CATEGORIES.map((c) => (
                      <option key={c} value={c}>
                        {c}
                      </option>
                    ))}
                  </select>
                </div>
                <div className="space-y-2">
                  <Label htmlFor="license">License</Label>
                  <Input
                    id="license"
                    value={license}
                    onChange={(e) => setLicense(e.target.value)}
                  />
                </div>
                <div className="space-y-2 sm:col-span-2">
                  <Label htmlFor="tags">Tags (comma-separated)</Label>
                  <Input id="tags" value={tags} onChange={(e) => setTags(e.target.value)} />
                </div>
                <div className="space-y-2 sm:col-span-2">
                  <label className="flex items-center gap-3 text-sm">
                    <input
                      type="checkbox"
                      checked={privateOnly}
                      disabled={savedListing?.privateOnly || saveListing.isPending}
                      onChange={(e) => setPrivateOnly(e.target.checked)}
                      aria-describedby="private-only-hint"
                      className="h-4 w-4 rounded border-border accent-crimson disabled:cursor-not-allowed"
                    />
                    <strong>Private games only</strong>
                  </label>
                  <p id="private-only-hint" className="text-xs text-muted-foreground">
                    For mods that may give an unfair gameplay advantage. Once saved, only RSMM
                    admins can remove this label.
                  </p>
                </div>
                <div className="space-y-2 sm:col-span-2">
                  <label className="flex cursor-pointer items-center gap-3 text-sm">
                    <input
                      type="checkbox"
                      checked={nsfw}
                      onChange={(e) => setNsfw(e.target.checked)}
                      className="h-4 w-4 rounded border-border accent-crimson"
                    />
                    <span className="text-sm font-medium leading-none">
                      <strong>NSFW / mature content</strong>
                    </span>
                  </label>
                  <p className="text-xs text-muted-foreground">
                    If checked, the mod will be hidden behind a blur by default.
                  </p>
                </div>
                <div className="space-y-2">
                  <Label htmlFor="repo">Repository URL</Label>
                  <Input
                    id="repo"
                    type="url"
                    value={repoUrl}
                    onChange={(e) => setRepoUrl(e.target.value)}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="home">Homepage URL</Label>
                  <Input
                    id="home"
                    type="url"
                    value={homepageUrl}
                    onChange={(e) => setHomepageUrl(e.target.value)}
                  />
                </div>
              </div>
            </section>
            <ScreenshotEditor gallery={gallery} />

            <section className="space-y-4">
              <h2 className="text-lg font-semibold">Videos</h2>
              {/* Videos */}
              <div className="space-y-2">
                <Label>Videos (YouTube or Vimeo URLs)</Label>
                {videos.length > 0 ? (
                  <ul className="space-y-2">
                    {videos.map((url, idx) => (
                      <li
                        key={url}
                        className="flex items-center gap-2 rounded-md border border-border/40 px-3 py-2"
                      >
                        <span className="flex-1 truncate font-data text-xs">{url}</span>
                        <Button
                          type="button"
                          size="sm"
                          variant="outline"
                          onClick={() => removeVideo(idx)}
                        >
                          remove
                        </Button>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="text-xs text-muted-foreground">No videos yet.</p>
                )}
                {videos.length < 8 ? (
                  <div className="flex gap-2">
                    <Input
                      value={videoInput}
                      onChange={(e) => setVideoInput((e.target as HTMLInputElement).value)}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') {
                          e.preventDefault();
                          addVideo();
                        }
                      }}
                      placeholder="https://www.youtube.com/watch?v=…"
                    />
                    <Button type="button" onClick={addVideo} disabled={!videoInput.trim()}>
                      Add
                    </Button>
                  </div>
                ) : null}
              </div>
            </section>
          </section>

          <section
            id="versions"
            aria-labelledby="versions-heading"
            tabIndex={-1}
            className="scroll-mt-[var(--editor-scroll-offset)] space-y-4 focus:outline-none"
          >
            <h2 id="versions-heading" className="text-lg font-semibold">
              Versions
            </h2>
            {removeVersion.isError ? (
              <p className="text-sm text-destructive">
                Could not delete that version
                {removeVersion.error instanceof Error ? `: ${removeVersion.error.message}` : ''}.
                Only the mod&apos;s owner can delete versions.
              </p>
            ) : null}
            {versions.length === 0 ? (
              <p className="text-sm text-muted-foreground">No versions published yet.</p>
            ) : (
              <ul className="space-y-3">
                {versions
                  .slice()
                  .sort((a, b) => new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime())
                  .map((v) => {
                    // changelog isn't on the published ModVersion schema yet
                    // because the public detail endpoint hasn't been
                    // extended — read it from manifestJson as a fallback.
                    const cl =
                      typeof v.manifestJson === 'object'
                        ? (v.manifestJson as { changelog?: string })?.changelog
                        : undefined;
                    return (
                      <li key={v.id} className="grimoire-card p-3">
                        <div className="flex items-center justify-between gap-2">
                          <div>
                            <p className="font-semibold">v{v.version}</p>
                            <p className="text-xs text-muted-foreground">
                              {fmtBytes(v.sizeBytes)} · {new Date(v.createdAt).toLocaleDateString()}
                            </p>
                          </div>
                          <div className="flex items-center gap-2">
                            <ScanBadge versionId={v.id} />
                            <Badge variant="outline">{v.sha256.slice(0, 12)}</Badge>
                            <Button
                              type="button"
                              variant="ghost"
                              size="sm"
                              className="text-destructive hover:text-destructive"
                              disabled={removeVersion.isPending}
                              aria-label={`Delete version ${v.version}`}
                              onClick={() => {
                                if (
                                  window.confirm(
                                    `Delete v${v.version} of "${mod.name}"? Its file is removed and nobody can download it any more. This cannot be undone.`,
                                  )
                                ) {
                                  removeVersion.mutate(v.id);
                                }
                              }}
                            >
                              <Trash2 className="h-3.5 w-3.5" aria-hidden />
                            </Button>
                          </div>
                        </div>
                        {v.scanStatus && v.scanStatus !== 'clean' && v.scanStatus !== 'skipped' ? (
                          <p
                            className={`mt-2 text-xs ${
                              v.scanStatus === 'flagged' ? 'text-destructive' : 'text-amber-500'
                            }`}
                          >
                            {v.scanStatus === 'flagged'
                              ? 'Flagged by malware scanning — the file was removed and this version cannot be downloaded.'
                              : 'In review — only you can see this version until the malware scan clears (usually a few minutes).'}
                          </p>
                        ) : null}
                        {cl ? (
                          <pre className="mt-2 whitespace-pre-wrap text-xs text-muted-foreground">
                            {cl}
                          </pre>
                        ) : null}
                      </li>
                    );
                  })}
              </ul>
            )}

            <div className="border-t border-border/40 pt-4">
              <h3 className="text-sm font-semibold">Ship a new version</h3>
              <div className="mt-3 grid gap-4 sm:grid-cols-2">
                <div className="space-y-2">
                  <Label htmlFor="newver">Version</Label>
                  <Input
                    id="newver"
                    value={newVersion}
                    onChange={(e) => setNewVersion(e.target.value)}
                    placeholder="0.2.0"
                    aria-invalid={
                      newVersion.length > 0 && !SEMVER_RE.test(newVersion) ? true : undefined
                    }
                  />
                  {newVersion.length > 0 && !SEMVER_RE.test(newVersion) ? (
                    <p className="text-xs text-destructive">
                      Must be semver, e.g. 0.2.0 (three numbers separated by dots).
                    </p>
                  ) : null}
                </div>
                <div className="space-y-2">
                  <Label htmlFor="newzip">New archive</Label>
                  <FileDrop
                    id="newzip"
                    accept=".zip,application/zip"
                    label="Mod archive (.zip)"
                    hint="up to 500 MB"
                    file={newZip}
                    onFile={setNewZip}
                    disabled={newVersionMut.isPending}
                  />
                </div>
                <div className="space-y-2 sm:col-span-2">
                  <Label>Changelog (Markdown)</Label>
                  <div data-color-mode="dark" className="md-editor-themed min-h-[200px]">
                    <MDEditor value={changelog} onChange={setChangelog} height={200} />
                  </div>
                </div>
              </div>
              {zipProgress ? (
                <ProgressBar
                  className="mt-4"
                  value={zipProgress.loaded}
                  max={zipProgress.total}
                  label={`Uploading ${fmtBytes(zipProgress.loaded)} of ${fmtBytes(zipProgress.total)}`}
                />
              ) : null}
              <div className="mt-4 flex items-center justify-end gap-3">
                {newVersionMut.isError ? (
                  <span className="text-xs text-destructive">
                    {describeApiError(newVersionMut.error)}
                  </span>
                ) : null}
                <Button
                  onClick={() => newVersionMut.mutate()}
                  disabled={!newZip || !SEMVER_RE.test(newVersion) || newVersionMut.isPending}
                >
                  {newVersionMut.isPending ? <Spinner /> : <Upload className="h-4 w-4" />} Publish
                  version
                </Button>
              </div>
            </div>
          </section>

          <section
            id="analytics"
            aria-label="Analytics"
            tabIndex={-1}
            className="scroll-mt-[var(--editor-scroll-offset)] focus:outline-none"
          >
            <ModStats slug={slug} />
          </section>
          <section
            id="team"
            aria-label="Team"
            tabIndex={-1}
            className="scroll-mt-[var(--editor-scroll-offset)] focus:outline-none"
          >
            <ModTeam slug={slug} />
          </section>

          <section
            id="danger"
            aria-labelledby="danger-heading"
            tabIndex={-1}
            className="scroll-mt-[var(--editor-scroll-offset)] space-y-3 focus:outline-none"
          >
            <div className="flex items-center gap-2">
              <AlertTriangle className="h-4 w-4 shrink-0 text-destructive" />
              <h2 id="danger-heading" className="text-lg font-semibold">
                Danger zone
              </h2>
            </div>
            <p className="text-sm text-muted-foreground">
              Deleting removes the mod row and every published version. The slug becomes available
              for someone else to claim. This cannot be undone.
            </p>
            <Button
              variant="destructive"
              onClick={() => {
                if (
                  window.confirm(
                    `Delete "${mod.name}" and all its versions? This cannot be undone.`,
                  )
                ) {
                  remove.mutate();
                }
              }}
              disabled={remove.isPending}
            >
              {remove.isPending ? <Spinner /> : <Trash2 className="h-4 w-4" />} Delete mod
            </Button>
            {remove.isError ? (
              <p className="text-xs text-destructive">{describeApiError(remove.error)}</p>
            ) : null}
          </section>
        </div>
      </div>
    </main>
  );
}
