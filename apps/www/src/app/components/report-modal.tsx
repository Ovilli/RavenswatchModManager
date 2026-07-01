'use client';
import { Button } from '@rsmm/ui';
import { useMutation } from '@tanstack/react-query';
import { Flag, X } from 'lucide-react';
import { useState } from 'react';
import { api } from '../../lib/api';

const REASONS: { value: string; label: string }[] = [
  { value: 'malware', label: 'Malware / virus' },
  { value: 'stolen', label: 'Stolen / copyrighted assets' },
  { value: 'broken', label: 'Broken / does not work' },
  { value: 'inappropriate', label: 'Inappropriate content' },
  { value: 'spam', label: 'Spam' },
  { value: 'other', label: 'Other' },
];

/** "Report this mod" button + modal. Available to everyone (reporting malware
 *  must not require an account). Posts to POST /api/mods/:slug/report. */
export function ReportModal({ slug }: { slug: string }) {
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState('malware');
  const [detail, setDetail] = useState('');
  const [done, setDone] = useState(false);

  const submit = useMutation({
    mutationFn: () => api.mods.report(slug, { reason, detail: detail.trim() || null }),
    onSuccess: () => setDone(true),
  });

  return (
    <>
      <Button
        variant="ghost"
        size="sm"
        className="text-muted-foreground"
        onClick={() => {
          setOpen(true);
          setDone(false);
        }}
      >
        <Flag className="mr-1.5 h-4 w-4" /> Report
      </Button>
      {open && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
          <div className="w-full max-w-md rounded-lg border border-border bg-background p-6 shadow-xl">
            <div className="mb-4 flex items-center justify-between">
              <h2 className="text-lg font-semibold">Report this mod</h2>
              <button type="button" onClick={() => setOpen(false)} aria-label="Close">
                <X className="h-5 w-5 text-muted-foreground" />
              </button>
            </div>

            {done ? (
              <div className="space-y-4">
                <p className="text-sm text-muted-foreground">
                  Thanks — your report was submitted and will be reviewed by a moderator.
                </p>
                <Button className="w-full" onClick={() => setOpen(false)}>
                  Close
                </Button>
              </div>
            ) : (
              <form
                className="space-y-4"
                onSubmit={(e) => {
                  e.preventDefault();
                  submit.mutate();
                }}
              >
                <label className="block text-sm">
                  <span className="mb-1 block text-muted-foreground">Reason</span>
                  <select
                    className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm"
                    value={reason}
                    onChange={(e) => setReason(e.target.value)}
                  >
                    {REASONS.map((r) => (
                      <option key={r.value} value={r.value}>
                        {r.label}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="block text-sm">
                  <span className="mb-1 block text-muted-foreground">Details (optional)</span>
                  <textarea
                    className="h-24 w-full resize-none rounded-md border border-border bg-background px-3 py-2 text-sm"
                    maxLength={2000}
                    value={detail}
                    onChange={(e) => setDetail(e.target.value)}
                    placeholder="What's wrong with this mod?"
                  />
                </label>
                {submit.isError && (
                  <p className="text-sm text-destructive">
                    Could not submit report. Please try again later.
                  </p>
                )}
                <Button type="submit" className="w-full" disabled={submit.isPending}>
                  {submit.isPending ? 'Submitting…' : 'Submit report'}
                </Button>
              </form>
            )}
          </div>
        </div>
      )}
    </>
  );
}
