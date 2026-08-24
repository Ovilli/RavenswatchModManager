'use client';

import type { PrivacySettings, TelemetryLevel } from '@rsmm/schemas';
import { Card, CardContent, CardDescription, CardHeader, CardTitle, Spinner } from '@rsmm/ui';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import Link from 'next/link';
import { api } from '../../lib/api';

const LEVELS: { value: TelemetryLevel; label: string; hint: string }[] = [
  {
    value: 'off',
    label: 'Don’t send',
    hint: 'Nothing is stored. The report is discarded when it arrives.',
  },
  {
    value: 'anonymous',
    label: 'Send anonymously',
    hint: 'Stored without your account id, so it counts toward totals but is not traceable to you.',
  },
  {
    value: 'linked',
    label: 'Send linked to my account',
    hint: 'Keeps your account id attached, so a maintainer can follow up with you about a specific report.',
  },
];

function LevelChoice({
  name,
  title,
  description,
  value,
  onChange,
  disabled,
}: {
  name: string;
  title: string;
  description: string;
  value: TelemetryLevel;
  onChange: (v: TelemetryLevel) => void;
  disabled: boolean;
}) {
  return (
    <fieldset className="space-y-2" disabled={disabled}>
      <legend className="text-sm font-medium text-foreground">{title}</legend>
      <p className="text-xs text-muted-foreground">{description}</p>
      <div className="space-y-1.5 pt-1">
        {LEVELS.map((l) => (
          <label
            key={l.value}
            className="flex cursor-pointer items-start gap-2.5 rounded-md border border-border/70 px-3 py-2 text-sm transition-colors hover:bg-accent/40 has-[:checked]:border-crimson/50 has-[:checked]:bg-crimson/5"
          >
            <input
              type="radio"
              name={name}
              value={l.value}
              checked={value === l.value}
              onChange={() => onChange(l.value)}
              className="mt-1 accent-current"
            />
            <span className="min-w-0">
              <span className="block font-medium">{l.label}</span>
              <span className="block text-xs text-muted-foreground">{l.hint}</span>
            </span>
          </label>
        ))}
      </div>
    </fieldset>
  );
}

function Toggle({
  label,
  hint,
  checked,
  onChange,
  disabled,
}: {
  label: string;
  hint: string;
  checked: boolean;
  onChange: (v: boolean) => void;
  disabled: boolean;
}) {
  return (
    <label className="flex cursor-pointer items-start gap-2.5 text-sm">
      <input
        type="checkbox"
        checked={checked}
        disabled={disabled}
        onChange={(e) => onChange(e.target.checked)}
        className="mt-1 accent-current"
      />
      <span className="min-w-0">
        <span className="block font-medium text-foreground">{label}</span>
        <span className="block text-xs text-muted-foreground">{hint}</span>
      </span>
    </label>
  );
}

/**
 * Account-level privacy choices.
 *
 * These are enforced by the API, not by the client: the telemetry routes read
 * the stored level before writing a row, so turning a stream off applies to
 * every device you are signed in on — including one running an older build.
 * Each control saves on change (one PATCH per toggle) rather than behind a Save
 * button, because a half-applied privacy form is worse than a slow one.
 */
export function PrivacyPanel() {
  const qc = useQueryClient();
  const prefs = useQuery({
    queryKey: ['me', 'privacy'],
    queryFn: () => api.me.privacy(),
    retry: false,
  });

  const save = useMutation({
    mutationFn: (patch: Partial<PrivacySettings>) => api.me.updatePrivacy(patch),
    // Trust the server's echo rather than the optimistic value — if a field is
    // rejected the UI must show what was actually stored.
    onSuccess: (next) => qc.setQueryData(['me', 'privacy'], next),
  });

  const p = prefs.data;
  const busy = save.isPending;

  return (
    <Card className="grimoire-card">
      <CardHeader>
        <CardTitle>Privacy &amp; data sharing</CardTitle>
        <CardDescription>
          What leaves your machine, and what other people can see. Applies to every device you sign
          in on. See the{' '}
          <Link href="/privacy" className="underline underline-offset-2 hover:text-foreground">
            privacy policy
          </Link>{' '}
          for what each stream contains.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-6">
        {prefs.isLoading ? (
          <Spinner />
        ) : !p ? (
          <p className="text-sm text-muted-foreground">Could not load your privacy settings.</p>
        ) : (
          <>
            <LevelChoice
              name="telemetryLevel"
              title="Usage reports"
              description="One ping when the manager applies mods: RSMM version, operating system, game build, whether it succeeded and how long it took. No file names, no mod list, no personal data."
              value={p.telemetryLevel}
              disabled={busy}
              onChange={(telemetryLevel) => save.mutate({ telemetryLevel })}
            />

            <LevelChoice
              name="crashReportLevel"
              title="Crash reports"
              description="Error type, message and stack trace when the desktop app hits an unhandled error. A stack trace can include file paths from your machine."
              value={p.crashReportLevel}
              disabled={busy}
              onChange={(crashReportLevel) => save.mutate({ crashReportLevel })}
            />

            <div className="space-y-3 border-t border-border/60 pt-5">
              <h3 className="text-sm font-medium text-foreground">What others can see</h3>
              <Toggle
                label="Public author profile"
                hint="Show your profile page at /u/<id> with your name, avatar and published mods. Turning this off returns a 404 for visitors; your mods stay listed in the registry under the author name you typed on each one."
                checked={p.publicProfile}
                disabled={busy}
                onChange={(publicProfile) => save.mutate({ publicProfile })}
              />
              <Toggle
                label="Public download counts"
                hint="Show how many times each of your mods has been downloaded. Turning this off hides the number everywhere public — you still see your own figures here and in My Mods, and site-wide totals still count them."
                checked={p.publicDownloadCounts}
                disabled={busy}
                onChange={(publicDownloadCounts) => save.mutate({ publicDownloadCounts })}
              />
            </div>

            <div className="space-y-3 border-t border-border/60 pt-5">
              <h3 className="text-sm font-medium text-foreground">Email</h3>
              <Toggle
                label="Release announcements"
                hint="Occasional email about new RSMM releases and notable mods. Off by default. Sign-in, password-reset and moderation email is not affected — that always sends."
                checked={p.emailAnnouncements}
                disabled={busy}
                onChange={(emailAnnouncements) => save.mutate({ emailAnnouncements })}
              />
            </div>

            <p className="text-xs text-muted-foreground">
              {save.isPending
                ? 'Saving…'
                : save.isError
                  ? 'Could not save that change — it has been reverted to the stored value.'
                  : 'Changes save immediately.'}
            </p>
          </>
        )}
      </CardContent>
    </Card>
  );
}
