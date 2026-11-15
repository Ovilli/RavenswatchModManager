'use client';
import { buttonVariants } from '@rsmm/ui';
import { useState } from 'react';
import { api } from '../../lib/api';

type Result = { slug: string; labelled: boolean; reasons: string[]; error?: string };

/**
 * Runs the store's own "Private games only" check over every published mod
 * (new uploads are checked by themselves; this is for mods published before
 * the check existed). Batches of 10 until the API says there are no more.
 */
export function PrivateOnlyCheck() {
  const [running, setRunning] = useState(false);
  const [checked, setChecked] = useState(0);
  const [results, setResults] = useState<Result[] | null>(null);
  const [failure, setFailure] = useState<string | null>(null);

  const run = async () => {
    setRunning(true);
    setFailure(null);
    setChecked(0);
    const all: Result[] = [];
    try {
      let offset: number | null = 0;
      while (offset !== null) {
        const page = await api.moderation.privateOnlyBackfill(offset);
        all.push(...page.results);
        setChecked(all.length);
        offset = page.next;
      }
      setResults(all);
    } catch (err) {
      setFailure(err instanceof Error ? err.message : String(err));
      setResults(all);
    } finally {
      setRunning(false);
    }
  };

  const labelled = results?.filter((r) => r.labelled) ?? [];
  const errors = results?.filter((r) => r.error) ?? [];

  return (
    <div className="space-y-3">
      <p className="text-sm text-muted-foreground">
        New uploads are checked automatically. This checks every mod already on the store and labels
        the ones that change the game. It only adds the label, never removes it.
      </p>
      <button
        type="button"
        disabled={running}
        onClick={() => void run()}
        className={buttonVariants({ variant: 'default', size: 'sm' })}
      >
        {running ? `Checking… ${checked} mods` : 'Check all mods for Private games only'}
      </button>
      {failure ? (
        <p className="rounded-md border border-destructive/50 bg-destructive/10 px-4 py-2.5 text-sm text-destructive">
          Stopped after {checked} mods: {failure}
        </p>
      ) : null}
      {results && !running ? (
        <div className="space-y-2 text-sm">
          <p>
            Checked {results.length} mods: {labelled.length} change the game
            {errors.length ? `, ${errors.length} could not be read` : ''}.
          </p>
          {labelled.length ? (
            <ul className="space-y-1">
              {labelled.map((r) => (
                <li key={r.slug}>
                  <span className="font-medium">{r.slug}</span>
                  <span className="text-muted-foreground">
                    {' '}
                    — {r.reasons.slice(0, 2).join('; ')}
                  </span>
                </li>
              ))}
            </ul>
          ) : null}
          {errors.length ? (
            <ul className="space-y-1 text-destructive">
              {errors.map((r) => (
                <li key={r.slug}>
                  {r.slug}: {r.error}
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
