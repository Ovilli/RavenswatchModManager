import { getDb, schema } from '@rsmm/db';
import { and, asc, eq, lt, or, sql } from 'drizzle-orm';
import { deleteObject, getObjectBytes, modUploadKey } from './storage.js';
import {
  MAX_VT_FILE_BYTES,
  VirusTotalRateLimitError,
  type VirusTotalStats,
  getVirusTotalAnalysis,
  submitVirusTotalFile,
  submitVirusTotalUrl,
} from './virus-total.js';

export type ScanStatus = 'queued' | 'pending' | 'clean' | 'flagged' | 'skipped' | 'error';

export interface ScanResult {
  status: ScanStatus;
  flagged: boolean;
  stats?: VirusTotalStats;
  analysisId?: string;
  permalink?: string;
  /** Set when a flagged object was purged from the bucket. */
  deleted?: boolean;
}

/** A version row's fields the scanner needs. */
export interface ScanTarget {
  id: string;
  slug: string;
  version: string;
  sha256: string;
  sizeBytes: number;
  assetUrl: string;
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

/**
 * Poll a submitted analysis a few times and return the last known verdict.
 * Free-tier is 4 lookups/min, so keep to <=3 polls (submit + 3 = 4 lookups)
 * and bail on a 429. Fail-open: a null/partial result never blocks — the
 * caller only treats a positive detection as a reason to remove a version.
 */
async function pollVerdict(
  analysisId: string,
): Promise<{ status: string; stats: VirusTotalStats } | null> {
  const delaysMs = [4000, 6000, 8000];
  let last: { status: string; stats: VirusTotalStats } | null = null;
  for (const d of delaysMs) {
    await sleep(d);
    let v: { status: string; stats: VirusTotalStats };
    try {
      v = await getVirusTotalAnalysis(analysisId);
    } catch (err) {
      if (err instanceof VirusTotalRateLimitError) break;
      throw err;
    }
    last = v;
    // A completed verdict is final; a positive detection is actionable even
    // mid-scan, so stop polling as soon as either is true.
    if (v.status === 'completed' || v.stats.malicious > 0 || v.stats.suspicious > 0) break;
  }
  return last;
}

/**
 * Submit a version to VirusTotal, wait for a verdict, and persist it.
 *
 * Stronger scan: for archives within MAX_VT_FILE_BYTES we upload the actual
 * bytes (`/api/v3/files`) so every AV engine runs on the exact file (and its
 * unpacked members); larger archives fall back to URL-scan of the public
 * bucket object.
 *
 * Removal: a positive detection deletes the object from the bucket (it is
 * world-readable, so hiding the DB row alone would leave the malware
 * downloadable at its direct URL) and marks the row 'flagged'.
 *
 * Fail-open everywhere else: queued / rate-limited / transient errors leave
 * the version visible so a slow or flaky scanner never disappears a legit mod.
 */
export async function scanVersion(target: ScanTarget): Promise<ScanResult> {
  const db = getDb();
  const key = modUploadKey(target.slug, target.version, target.sha256);

  let analysis: { analysisId: string; permalink: string };
  // Prefer a real file-upload scan when the archive is small enough.
  if (target.sizeBytes > 0 && target.sizeBytes <= MAX_VT_FILE_BYTES) {
    const bytes = await getObjectBytes(key, MAX_VT_FILE_BYTES);
    analysis = bytes
      ? await submitVirusTotalFile(bytes, `${target.slug}-${target.version}.zip`)
      : await submitVirusTotalUrl(target.assetUrl);
  } else {
    analysis = await submitVirusTotalUrl(target.assetUrl);
  }

  const verdict = await pollVerdict(analysis.analysisId);
  const stats = verdict?.stats ?? null;
  const flagged = !!stats && (stats.malicious > 0 || stats.suspicious > 0);
  const resolved = verdict?.status === 'completed';
  const status: ScanStatus = flagged ? 'flagged' : resolved ? 'clean' : 'pending';

  let deleted = false;
  if (flagged) {
    try {
      await deleteObject(key);
      deleted = true;
    } catch (err) {
      // A failed delete must not swallow the flag — the row still goes
      // 'flagged' (hidden + download blocked). Surface for follow-up.
      console.error('failed to purge flagged object', { key, err: String(err) });
    }
  }

  await db
    .update(schema.modVersions)
    .set({
      scanStatus: status,
      scanId: analysis.analysisId,
      scanStats: stats ? ({ ...stats } as Record<string, number>) : undefined,
      scannedAt: new Date(),
    })
    .where(eq(schema.modVersions.id, target.id));

  return {
    status,
    flagged,
    stats: stats ?? undefined,
    analysisId: analysis.analysisId,
    permalink: analysis.permalink,
    deleted,
  };
}

/** Persist a terminal state without contacting VirusTotal. */
export async function markScan(versionId: string, status: ScanStatus): Promise<void> {
  const db = getDb();
  await db
    .update(schema.modVersions)
    .set({ scanStatus: status, scannedAt: new Date() })
    .where(eq(schema.modVersions.id, versionId));
}

// ─────────────────────────────────────────────────────────────────────
// Scan queue. Publishing no longer scans inline (the free tier is 4
// lookups/min and a scan can take ~18s); it enqueues, and an in-process
// worker (see index.ts) drains one item per tick so publish is instant and
// the rate limit is never blown.
// ─────────────────────────────────────────────────────────────────────

/** Seconds between worker ticks — one scan (<=4 VT lookups) per tick keeps us
 *  inside the 4-lookups/min free-tier budget. Also the unit for ETA math. */
export const SCAN_TICK_SECONDS = 60;

/** Re-scan a clean/errored version once it's older than this, so newer VT
 *  signatures catch malware that was undetectable at upload time. */
const RESCAN_AFTER_MS = 7 * 24 * 60 * 60 * 1000;

/** Mark a version as waiting for the scan worker. */
export async function enqueueScan(versionId: string): Promise<void> {
  const db = getDb();
  await db
    .update(schema.modVersions)
    .set({ scanStatus: 'queued', scanQueuedAt: new Date(), scannedAt: null })
    .where(eq(schema.modVersions.id, versionId));
}

export interface QueueInfo {
  status: ScanStatus;
  /** 1-based place in the queue (only meaningful while status === 'queued'). */
  position: number | null;
  /** Rough seconds until this version is scanned. */
  etaSeconds: number | null;
  stats?: Record<string, number>;
}

/** Current queue state for one version: status + place in line + ETA. */
export async function queueInfo(versionId: string): Promise<QueueInfo | null> {
  const db = getDb();
  const rows = await db
    .select({
      status: schema.modVersions.scanStatus,
      queuedAt: schema.modVersions.scanQueuedAt,
      stats: schema.modVersions.scanStats,
    })
    .from(schema.modVersions)
    .where(eq(schema.modVersions.id, versionId))
    .limit(1);
  const row = rows[0];
  if (!row) return null;

  if (row.status !== 'queued' || !row.queuedAt) {
    return {
      status: row.status as ScanStatus,
      position: null,
      etaSeconds: null,
      stats: row.stats ?? undefined,
    };
  }

  // Position = how many queued rows are ahead of this one (older queuedAt).
  const ahead = await db
    .select({ n: sql<number>`count(*)::int` })
    .from(schema.modVersions)
    .where(
      and(
        eq(schema.modVersions.scanStatus, 'queued'),
        lt(schema.modVersions.scanQueuedAt, row.queuedAt),
      ),
    );
  const position = (ahead[0]?.n ?? 0) + 1;
  return {
    status: 'queued',
    position,
    etaSeconds: position * SCAN_TICK_SECONDS,
    stats: row.stats ?? undefined,
  };
}

/**
 * One unit of worker work: scan the oldest queued version; if the queue is
 * empty, re-scan the least-recently-scanned stale version. Returns a short
 * description of what it did (or null when there was nothing to do).
 *
 * A rate-limit while submitting leaves the row queued so the next tick retries.
 */
export async function drainOnce(): Promise<{ id: string; action: string; status?: string } | null> {
  const db = getDb();

  const pickTarget = async () => {
    // 1) Oldest queued upload.
    const queued = await selectTarget(
      and(eq(schema.modVersions.scanStatus, 'queued')),
      asc(sql`${schema.modVersions.scanQueuedAt} nulls last`),
    );
    if (queued) return { target: queued, action: 'scan' as const };
    // 2) Otherwise a stale clean/error row due for a refresh.
    const cutoff = new Date(Date.now() - RESCAN_AFTER_MS);
    const stale = await selectTarget(
      and(
        or(eq(schema.modVersions.scanStatus, 'clean'), eq(schema.modVersions.scanStatus, 'error')),
        lt(schema.modVersions.scannedAt, cutoff),
      ),
      asc(sql`${schema.modVersions.scannedAt} nulls first`),
    );
    if (stale) return { target: stale, action: 'rescan' as const };
    return null;
  };

  const picked = await pickTarget();
  if (!picked) return null;

  try {
    const r = await scanVersion(picked.target);
    return { id: picked.target.id, action: picked.action, status: r.status };
  } catch (err) {
    if (err instanceof VirusTotalRateLimitError) {
      // Leave it in place (queued rows stay queued) and retry next tick.
      return { id: picked.target.id, action: `${picked.action}:rate-limited` };
    }
    console.error('scan worker error', { versionId: picked.target.id, err: String(err) });
    await markScan(picked.target.id, 'error');
    return { id: picked.target.id, action: `${picked.action}:error` };
  }
}

async function selectTarget(
  where: ReturnType<typeof and>,
  order: ReturnType<typeof asc>,
): Promise<ScanTarget | null> {
  const db = getDb();
  const rows = await db
    .select({
      id: schema.modVersions.id,
      slug: schema.mods.slug,
      version: schema.modVersions.version,
      sha256: schema.modVersions.sha256,
      sizeBytes: schema.modVersions.sizeBytes,
      assetUrl: schema.modVersions.assetUrl,
    })
    .from(schema.modVersions)
    .innerJoin(schema.mods, eq(schema.modVersions.modId, schema.mods.id))
    .where(where)
    .orderBy(order)
    .limit(1);
  return rows[0] ?? null;
}
