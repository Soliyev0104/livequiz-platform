'use client';

import * as React from 'react';

import { remainingMs, windowMs } from '@/lib/clock';

export interface Countdown {
  remainingMs: number;
  remainingSeconds: number;
  totalMs: number;
  /** 0..100 — fraction of time remaining. */
  percent: number;
  expired: boolean;
}

export function useCountdown(
  startedAt: string | null | undefined,
  deadlineAt: string | null | undefined,
  skewMs: number,
): Countdown {
  const compute = React.useCallback((): Countdown => {
    if (!deadlineAt) {
      return { remainingMs: 0, remainingSeconds: 0, totalMs: 0, percent: 0, expired: true };
    }
    const total = startedAt ? windowMs(startedAt, deadlineAt) : 0;
    const rem = remainingMs(deadlineAt, skewMs);
    const percent = total > 0 ? Math.max(0, Math.min(100, (rem / total) * 100)) : rem > 0 ? 100 : 0;
    return {
      remainingMs: rem,
      remainingSeconds: Math.ceil(rem / 1000),
      totalMs: total,
      percent,
      expired: rem <= 0,
    };
  }, [startedAt, deadlineAt, skewMs]);

  const [state, setState] = React.useState<Countdown>(compute);

  React.useEffect(() => {
    setState(compute());
    if (!deadlineAt) return;
    const id = setInterval(() => setState(compute()), 200);
    return () => clearInterval(id);
  }, [compute, deadlineAt]);

  return state;
}
