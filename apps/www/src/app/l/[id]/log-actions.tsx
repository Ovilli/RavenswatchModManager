'use client';

import { Button } from '@rsmm/ui';
import { Check, Copy, Download } from 'lucide-react';
import { useState } from 'react';

/** Copy / download controls for a shared log. Client-only because both need
 *  browser APIs; the log itself is rendered on the server as plain text. */
export function LogActions({ content, filename }: { content: string; filename: string }) {
  const [copied, setCopied] = useState(false);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(content);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Clipboard is permission-gated; the text is on screen and selectable
      // either way, so a failure needs no error state of its own.
    }
  };

  const download = () => {
    const url = URL.createObjectURL(new Blob([content], { type: 'text/plain' }));
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="mt-6 flex flex-wrap gap-2">
      <Button type="button" variant="outline" size="sm" onClick={() => void copy()}>
        {copied ? (
          <Check className="mr-1.5 h-3.5 w-3.5" />
        ) : (
          <Copy className="mr-1.5 h-3.5 w-3.5" />
        )}
        {copied ? 'Copied' : 'Copy'}
      </Button>
      <Button type="button" variant="outline" size="sm" onClick={download}>
        <Download className="mr-1.5 h-3.5 w-3.5" />
        Download
      </Button>
    </div>
  );
}
