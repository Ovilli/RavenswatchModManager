import React from 'react';

export function AboutIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg" aria-hidden>
      <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="1.8" fill="currentColor" fillOpacity="0.04" />
      <path d="M12 16v-4" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
      <path d="M12 8h.01" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
    </svg>
  );
}

export default AboutIcon;
