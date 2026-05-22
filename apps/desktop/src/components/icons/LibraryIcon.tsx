export function LibraryIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg" aria-hidden>
      <title>Library</title>
      <rect
        x="3"
        y="4"
        width="18"
        height="16"
        stroke="currentColor"
        strokeWidth="1.8"
        rx="1.6"
        fill="currentColor"
        fillOpacity="0.06"
      />
      <path d="M7 4v16" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
      <path d="M17 4v16" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
    </svg>
  );
}

