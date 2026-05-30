export function ConflictsIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg" aria-hidden>
      <title>Conflicts</title>
      <path
        d="M10.29 3.86L1.82 12.33a2 2 0 0 0 0 2.83l7.77 7.77a2 2 0 0 0 2.83 0l8.47-8.47a2 2 0 0 0 0-2.83L13.12 3.86a2 2 0 0 0-2.83 0z"
        stroke="currentColor"
        strokeWidth="1.6"
        fill="currentColor"
        fillOpacity="0.04"
      />
      <path d="M12 9v4" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
      <path d="M12 17h.01" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
    </svg>
  );
}
