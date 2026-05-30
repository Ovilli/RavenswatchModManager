export function LibraryIcon({ className }: { className?: string }) {
  return (
    <svg
      className={className}
      viewBox="0 0 24 24"
      xmlns="http://www.w3.org/2000/svg"
      role="img"
      aria-label="Library"
    >
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

export function BrowseIcon({ className }: { className?: string }) {
  return (
    <svg
      className={className}
      viewBox="0 0 24 24"
      xmlns="http://www.w3.org/2000/svg"
      role="img"
      aria-label="Browse"
    >
      <title>Browse</title>
      <circle
        cx="11"
        cy="11"
        r="7"
        stroke="currentColor"
        strokeWidth="1.8"
        fill="currentColor"
        fillOpacity="0.06"
      />
      <path
        d="M21 21l-4.35-4.35"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

export function ProfilesIcon({ className }: { className?: string }) {
  return (
    <svg
      className={className}
      viewBox="0 0 24 24"
      xmlns="http://www.w3.org/2000/svg"
      role="img"
      aria-label="Profiles"
    >
      <title>Profiles</title>
      <circle
        cx="12"
        cy="8"
        r="4"
        stroke="currentColor"
        strokeWidth="1.8"
        fill="currentColor"
        fillOpacity="0.06"
      />
      <path
        d="M4 20a8 8 0 0 1 16 0"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
      />
    </svg>
  );
}

export function ConflictsIcon({ className }: { className?: string }) {
  return (
    <svg
      className={className}
      viewBox="0 0 24 24"
      xmlns="http://www.w3.org/2000/svg"
      role="img"
      aria-label="Conflicts"
    >
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

export function SettingsIcon({ className }: { className?: string }) {
  return (
    <svg
      className={className}
      viewBox="0 0 24 24"
      xmlns="http://www.w3.org/2000/svg"
      role="img"
      aria-label="Settings"
    >
      <title>Settings</title>
      <path
        fill="currentColor"
        d="M19.14 12.94a7.14 7.14 0 0 0 0-1.88l2.03-1.58a0.5 0.5 0 0 0 .12-0.64l-1.92-3.32a0.5 0.5 0 0 0-.6-0.22l-2.39 0.96a7.1 7.1 0 0 0-1.6-.93L14.5 2.47a0.5 0.5 0 0 0-.5-0.47h-4a0.5 0.5 0 0 0-.5 0.47l-.38 2.19a7.1 7.1 0 0 0-1.6.93L4.15 5.63a0.5 0.5 0 0 0-.6.22L1.62 9.17a0.5 0.5 0 0 0 .12.64l2.03 1.58a7.14 7.14 0 0 0 0 1.88L1.74 14.5a0.5 0.5 0 0 0-.12.64l1.92 3.32a0.5 0.5 0 0 0 .6.22l2.39-.96c.5.37 1.04.67 1.6.93l.38 2.19a0.5 0.5 0 0 0 .5.47h4a0.5 0.5 0 0 0 .5-.47l.38-2.19c.56-.26 1.1-.56 1.6-.93l2.39.96a0.5 0.5 0 0 0 .6-.22l1.92-3.32a0.5 0.5 0 0 0-.12-.64l-2.03-1.58zM12 15.5A3.5 3.5 0 1 1 12 8.5a3.5 3.5 0 0 1 0 7z"
      />
    </svg>
  );
}

export function AboutIcon({ className }: { className?: string }) {
  return (
    <svg
      className={className}
      viewBox="0 0 24 24"
      xmlns="http://www.w3.org/2000/svg"
      role="img"
      aria-label="About"
    >
      <title>About</title>
      <circle
        cx="12"
        cy="12"
        r="10"
        stroke="currentColor"
        strokeWidth="1.8"
        fill="currentColor"
        fillOpacity="0.04"
      />
      <path d="M12 16v-4" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
      <path d="M12 8h.01" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
    </svg>
  );
}
