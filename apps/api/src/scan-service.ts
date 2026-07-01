import { getDb, schema } from '@rsmm/db';
import { eq } from 'drizzle-orm';
import { deleteObject, getObjectBytes, modUploadKey } from './storage.js';
import {
  MAX_VT_FILE_BYTES,
  VirusTotalRateLimitError,
  type VirusTotalStats,
  getVirusTotalAnalysis,
  submitVirusTotalFile,
  submitVirusTotalUrl,
} from './virus-total.js';

export type ScanStatus = 'pending' | 'clean' | 'flagged' | 'skipped' | 'error';

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
