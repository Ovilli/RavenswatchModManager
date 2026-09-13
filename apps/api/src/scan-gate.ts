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
export function isServable(status: string | null | undefined): boolean {
  return status === 'clean' || status === 'skipped';
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
