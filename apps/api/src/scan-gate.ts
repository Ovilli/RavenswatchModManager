// Pure malware-scan gate. Kept dependency-free (no DB, no env, no storage) so
// the security-critical fail-closed invariant can be unit-tested in isolation —
// importing scan-service.ts pulls the whole DB/env chain, which throws in CI
// without DATABASE_URL. scan-service re-exports these so callers are unchanged.

export type ScanStatus = 'queued' | 'pending' | 'clean' | 'flagged' | 'skipped' | 'error';

/**
 * Whether a version may be served to the public. Fail-CLOSED: only versions
 * that were actually scanned clean, or explicitly skipped because scanning is
 * disabled server-side, are downloadable. Everything else — 'pending' (freshly
 * uploaded, not yet scanned), 'queued', 'flagged', and 'error' — is withheld so
 * there is no window in which un-scanned bytes are downloadable. The rescan
 * loop revisits 'error' rows, so a transient scan failure self-heals.
 */
export const SERVABLE_STATUSES = ['clean', 'skipped'] as const;

export function isServable(status: string | null | undefined): boolean {
  return (SERVABLE_STATUSES as readonly string[]).includes(status ?? '');
}

/**
 * Scan columns written by every re-presign of an existing (mod, version) row.
 *
 * A re-presign points the row at NEW bytes (the object key embeds the sha256),
 * so whatever verdict the row carried belonged to a different file. Leaving it
 * in place let a publisher get `1.0.0` scanned clean, re-presign `1.0.0` with a
 * different sha, PUT anything to the new key and have it served at once under
 * the old 'clean' — never calling /scan at all.
 */
export const RESET_SCAN_FIELDS = {
  scanStatus: 'pending',
  scanId: null,
  scanStats: null,
  scanQueuedAt: null,
  scannedAt: null,
} as const;

/**
 * Whether a version row may be pointed at new bytes. A servable version is
 * immutable: its bytes are already on users' machines under that version
 * number, so a change must be a new version. Everything else (a failed PUT
 * being retried, a flagged or errored build being replaced) may re-presign,
 * and is reset to 'pending' by RESET_SCAN_FIELDS so the gate runs again.
 */
export function canReplaceVersionBytes(status: string | null | undefined): boolean {
  return !isServable(status);
}

/**
 * Whether the bytes the scanner read are the bytes the version row promises.
 *
 * Clients install a version only if the download hashes to the row's `sha256`,
 * so a verdict is only worth something for exactly those bytes. The scanner
 * used to hash what the bucket held and scan THAT, without comparing: a
 * publisher could declare the hash of their payload, get a padded benign file
 * of the same length scanned clean (the presign binds the length; whether the
 * store enforces the query-string checksum is the store's business), then PUT
 * the payload to the still-valid URL. Clients then accept it, since it matches
 * the declared hash. Refusing a mismatch means a verdict always covers the
 * bytes clients will accept.
 */
export function storedBytesMatchDeclared(storedSha256: string, declaredSha256: string): boolean {
  return storedSha256.toLowerCase() === declaredSha256.toLowerCase();
}

/**
 * Per-instance single-flight lock for the scan drain, with a lease.
 *
 * A plain boolean was not enough on serverless. A drain kicked off detached
 * (after a publish or a status poll) is frozen by the platform the moment the
 * response is sent; its promise never settles, so the flag stayed `true` for
 * the life of the instance and every later drain — the scheduled cron one
 * included — returned "nothing to do" in milliseconds while a version sat
 * queued. The lease makes an abandoned hold expire, and `force` lets a drain
 * that is awaited for its whole request (the cron) run regardless: at worst it
 * repeats a frozen scan, which VirusTotal dedupes and the verdict write
 * tolerates.
 */
export class DrainLock {
  private heldSince: number | null = null;

  constructor(private readonly leaseMs: number) {}

  /** Take the lock. False when a live (unexpired) drain holds it. */
  tryAcquire(now: number, force = false): boolean {
    if (!force && this.heldSince !== null && now - this.heldSince < this.leaseMs) {
      return false;
    }
    this.heldSince = now;
    return true;
  }

  /** Release only the hold that `acquiredAt` took, so a stale drain finishing
   *  late cannot drop a newer drain's lock. */
  release(acquiredAt: number): void {
    if (this.heldSince === acquiredAt) this.heldSince = null;
  }
}
