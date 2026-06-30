'use client';

import { useState } from 'react';
import { faqs } from './faq-data';

export function FAQ() {
  const [open, setOpen] = useState<number | null>(null);

  return (
    <div className="space-y-3">
      {faqs.map((faq, i) => {
        const isOpen = open === i;
        return (
          <div key={faq.q} className="grimoire-card overflow-hidden">
            <button
              type="button"
              onClick={() => setOpen(isOpen ? null : i)}
              className="flex w-full items-center justify-between px-6 py-4 text-left text-sm font-medium text-foreground transition-colors hover:text-parchment/90"
            >
              <span>{faq.q}</span>
              <span
                className={`ml-4 shrink-0 text-gilt/60 transition-transform duration-200 ${isOpen ? 'rotate-180' : ''}`}
              >
                ▼
              </span>
            </button>
            {isOpen && (
              <div className="border-t border-border/40 px-6 pb-4 pt-3 text-sm text-muted-foreground">
                {faq.a}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
