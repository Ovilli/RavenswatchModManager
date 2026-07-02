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
