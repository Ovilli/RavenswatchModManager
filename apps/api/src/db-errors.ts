export function isPgErrorCode(err: unknown, code: string): boolean {
  if (!err || typeof err !== 'object') return false;
  const top = err as { code?: unknown; cause?: unknown };
  if (top.code === code) return true;
  const cause = top.cause;
  if (cause && typeof cause === 'object' && (cause as { code?: unknown }).code === code) {
    return true;
  }
  return false;
}
