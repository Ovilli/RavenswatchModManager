import { cn } from '../lib/cn';

interface ProgressBarProps {
  value: number;
  max: number;
  className?: string;
  label?: string;
  /** Show an animated indeterminate bar when value/max are irrelevant. */
  indeterminate?: boolean;
}

export function ProgressBar({ value, max, className, label, indeterminate }: ProgressBarProps) {
  const pct = indeterminate ? 0 : max > 0 ? Math.round((value / max) * 100) : 0;
  return (
    <div className={cn('flex items-center gap-3', className)}>
      <div className="h-2 flex-1 overflow-hidden rounded-full bg-muted">
        <div
          className={cn(
            'h-full rounded-full bg-primary transition-all duration-300',
            indeterminate && 'w-1/2 animate-pulse',
          )}
          style={{ width: indeterminate ? undefined : `${pct}%` }}
        />
      </div>
      {label ? <span className="shrink-0 text-xs text-muted-foreground whitespace-nowrap">{label}</span> : null}
      {!label && !indeterminate ? (
        <span className="shrink-0 text-xs text-muted-foreground tabular-nums">{pct}%</span>
      ) : null}
    </div>
  );
}
