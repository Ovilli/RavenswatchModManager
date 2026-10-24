'use client';
import { cn } from '@rsmm/ui';
import { Upload, X } from 'lucide-react';
import { useEffect, useState } from 'react';
import { fmtBytes } from '../../lib/upload';

/**
 * Drag-and-drop file picker. Click or drop to choose; the chosen file shows
 * with its size (and a thumbnail when `preview` and it's an image) and can be
 * cleared. A real <input type="file"> sits underneath, so keyboard and screen
 * readers get the native control.
 */
export function FileDrop({
  id,
  accept,
  label,
  hint,
  file,
  onFile,
  preview = false,
  disabled = false,
}: {
  id: string;
  accept: string;
  label: string;
  hint?: string;
  file: File | null;
  onFile: (file: File | null) => void;
  preview?: boolean;
  disabled?: boolean;
}) {
  const [over, setOver] = useState(false);
  const [thumb, setThumb] = useState<string | null>(null);

  useEffect(() => {
    if (!preview || !file || !file.type.startsWith('image/')) {
      setThumb(null);
      return;
    }
    const url = URL.createObjectURL(file);
    setThumb(url);
    return () => URL.revokeObjectURL(url);
  }, [file, preview]);

  if (file) {
    return (
      <div className="flex items-center gap-3 rounded-lg border border-border bg-card/60 p-3">
        {thumb ? (
          <img src={thumb} alt="" className="h-14 w-20 shrink-0 rounded object-cover" />
        ) : (
          <Upload className="h-5 w-5 shrink-0 text-gilt" aria-hidden="true" />
        )}
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-medium">{file.name}</p>
          <p className="text-xs text-muted-foreground">{fmtBytes(file.size)}</p>
        </div>
        <button
          type="button"
          onClick={() => onFile(null)}
          disabled={disabled}
          aria-label={`Remove ${file.name}`}
          className="rounded p-1.5 text-muted-foreground transition hover:bg-foreground/10 hover:text-foreground disabled:opacity-50"
        >
          <X className="h-4 w-4" />
        </button>
      </div>
    );
  }

  return (
    <label
      htmlFor={id}
      onDragOver={(e) => {
        e.preventDefault();
        setOver(true);
      }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => {
        e.preventDefault();
        setOver(false);
        const dropped = e.dataTransfer.files?.[0];
        if (dropped && !disabled) onFile(dropped);
      }}
      className={cn(
        'flex cursor-pointer flex-col items-center justify-center gap-1 rounded-lg border-2 border-dashed px-4 py-6 text-center transition-colors focus-within:ring-2 focus-within:ring-ring',
        over ? 'border-gilt bg-gilt/5' : 'border-border hover:border-gilt/60 hover:bg-card/60',
        disabled && 'pointer-events-none opacity-50',
      )}
    >
      <Upload className="h-5 w-5 text-muted-foreground" aria-hidden="true" />
      <span className="text-sm font-medium">{label}</span>
      <span className="text-xs text-muted-foreground">
        Drop a file here or click to browse{hint ? ` · ${hint}` : ''}
      </span>
      <input
        id={id}
        type="file"
        accept={accept}
        disabled={disabled}
        onChange={(e) => onFile(e.target.files?.[0] ?? null)}
        className="sr-only"
      />
    </label>
  );
}
