import React from 'react';

export function WindowMaximizeIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" className={className} aria-hidden>
      <title>Maximize window</title>
      <rect x="4" y="4" width="16" height="16" rx="1.5" />
    </svg>
  );
}
