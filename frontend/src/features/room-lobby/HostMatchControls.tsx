'use client';

import { Pause, Play, Power, SkipForward, StepForward } from 'lucide-react';
import * as React from 'react';
import { toast } from 'sonner';

import { Button } from '@/components/ui/button';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import {
  useEndMatch,
  usePauseMatch,
  useResumeMatch,
  useStartMatch,
} from '@/features/room-lobby/hooks';
import { ApiError } from '@/lib/api-client';

interface HostMatchControlsProps {
  code: string;
  /** 'lobby' before start; 'running'/'paused' while live; 'completed' after end. */
  matchStatus: string | null;
  canStart: boolean;
}

export function HostMatchControls({ code, matchStatus, canStart }: HostMatchControlsProps): React.JSX.Element {
  const start = useStartMatch(code);
  const pause = usePauseMatch(code);
  const resume = useResumeMatch(code);
  const end = useEndMatch(code);

  const live = matchStatus === 'running' || matchStatus === 'paused';
  const paused = matchStatus === 'paused';
  const finished = matchStatus === 'completed' || matchStatus === 'cancelled';

  const run = React.useCallback(
    async (fn: () => Promise<unknown>, failMsg: string) => {
      try {
        await fn();
      } catch (err) {
        toast.error(err instanceof ApiError ? err.message : failMsg);
      }
    },
    [],
  );

  const togglePause = React.useCallback(() => {
    if (!live) return;
    if (paused) void run(() => resume.mutateAsync(), 'Could not resume the match');
    else void run(() => pause.mutateAsync(), 'Could not pause the match');
  }, [live, paused, resume, pause, run]);

  // Esc toggles pause/resume during a live match.
  React.useEffect(() => {
    function onKey(e: KeyboardEvent): void {
      if (e.key === 'Escape' && live) {
        e.preventDefault();
        togglePause();
      }
    }
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [live, togglePause]);

  if (finished) {
    return <p className="text-sm text-muted-foreground">Match complete.</p>;
  }

  if (!live) {
    return (
      <Button
        size="lg"
        className="w-full"
        disabled={!canStart || start.isPending}
        onClick={() => void run(() => start.mutateAsync(), 'Could not start the match')}
      >
        <Play className="h-5 w-5" /> Start match
      </Button>
    );
  }

  return (
    <div className="space-y-2">
      <div className="flex gap-2">
        <Button variant="outline" className="flex-1" onClick={togglePause} disabled={pause.isPending || resume.isPending}>
          {paused ? <Play className="h-4 w-4" /> : <Pause className="h-4 w-4" />}
          {paused ? 'Resume' : 'Pause'}
        </Button>
        <Button
          variant="destructive"
          className="flex-1"
          onClick={() => {
            if (window.confirm('End the match for everyone?')) {
              void run(() => end.mutateAsync(), 'Could not end the match');
            }
          }}
          disabled={end.isPending}
        >
          <Power className="h-4 w-4" /> End
        </Button>
      </div>
      <div className="flex gap-2">
        <Tooltip>
          <TooltipTrigger asChild>
            <span className="flex-1">
              <Button variant="ghost" className="w-full" disabled>
                <StepForward className="h-4 w-4" /> Next
              </Button>
            </span>
          </TooltipTrigger>
          <TooltipContent>Questions advance automatically when the timer runs out.</TooltipContent>
        </Tooltip>
        <Tooltip>
          <TooltipTrigger asChild>
            <span className="flex-1">
              <Button variant="ghost" className="w-full" disabled>
                <SkipForward className="h-4 w-4" /> Skip
              </Button>
            </span>
          </TooltipTrigger>
          <TooltipContent>Skipping is handled by the server timer in this build.</TooltipContent>
        </Tooltip>
      </div>
      <p className="text-center text-xs text-muted-foreground">
        Shortcut: <kbd className="rounded border bg-muted px-1">Esc</kbd> pause / resume
      </p>
    </div>
  );
}
