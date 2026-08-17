export function WindowRestoreIcon({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      aria-hidden
    >
      <title>Restore window</title>
      {/* Two overlapping windows, both on the same 1.5 corner radius and the
          same 4..20 box the maximize icon uses, so the pair does not appear to
          change weight or size when the button flips between them. */}
      <rect x="4" y="8" width="12" height="12" rx="1.5" />
      <path d="M8 8V5.5A1.5 1.5 0 0 1 9.5 4h9A1.5 1.5 0 0 1 20 5.5v9a1.5 1.5 0 0 1-1.5 1.5H16" />
    </svg>
  );
}
