'use client';

import * as React from 'react';

import { Progress } from '@/components/ui/progress';
import { useCountdown } from '@/features/live-match/useCountdown';
import { cn } from '@/lib/utils';

interface TimerBarProps {
  startedAt: string | null | undefined;
  deadlineAt: string | null | undefined;
  skewMs: number;
  /** When true, the question has closed — show a full but muted bar. */
  closed?: boolean;
  className?: string;
}

export function TimerBar({ startedAt, deadlineAt, skewMs, closed, className }: TimerBarProps): React.JSX.Element {
  const cd = useCountdown(startedAt, deadlineAt, skewMs);
  const pct = closed ? 0 : cd.percent;
  const urgent = !closed && cd.remainingMs <= 5000;
  return (
    <div className={cn('space-y-1', className)}>
      <Progress
        value={pct}
        indicatorClassName={cn(
          'transition-[width,background-color] duration-200',
          closed ? 'bg-muted-foreground/40' : urgent ? 'bg-destructive' : 'bg-primary',
        )}
      />
      <div className="flex justify-between text-xs text-muted-foreground">
        <span>{closed ? 'Question closed' : 'Time remaining'}</span>
        <span className={cn('font-mono tabular-nums', urgent && 'font-semibold text-destructive')}>
          {closed ? '0s' : `${cd.remainingSeconds}s`}
        </span>
      </div>
    </div>
  );
}
