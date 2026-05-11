'use client';

import { AnimatePresence, motion } from 'framer-motion';
import { Crown } from 'lucide-react';
import * as React from 'react';

import { cn } from '@/lib/utils';
import type { LeaderboardEntry } from '@/lib/types';

interface LeaderboardProps {
  entries: LeaderboardEntry[];
  highlightParticipantId?: string;
  emptyHint?: string;
  className?: string;
}

const MEDAL = ['bg-amber-400/20 text-amber-500', 'bg-zinc-300/20 text-zinc-300', 'bg-orange-400/20 text-orange-400'];

export function Leaderboard({
  entries,
  highlightParticipantId,
  emptyHint = 'No scores yet.',
  className,
}: LeaderboardProps): React.JSX.Element {
  if (entries.length === 0) {
    return <p className={cn('text-sm text-muted-foreground', className)}>{emptyHint}</p>;
  }
  return (
    <ol className={cn('space-y-1.5', className)}>
      <AnimatePresence initial={false}>
        {entries.map((e) => {
          const mine = highlightParticipantId && e.participant_id === highlightParticipantId;
          return (
            <motion.li
              key={e.participant_id}
              layout
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0 }}
              transition={{ type: 'spring', stiffness: 500, damping: 40 }}
              className={cn(
                'flex items-center gap-3 rounded-lg border px-3 py-2 text-sm',
                mine ? 'border-primary bg-primary/10' : 'border-border/60 bg-card',
              )}
            >
              <span
                className={cn(
                  'grid h-7 w-7 shrink-0 place-items-center rounded-full text-xs font-bold',
                  e.rank <= 3 ? MEDAL[e.rank - 1] : 'bg-muted text-muted-foreground',
                )}
              >
                {e.rank === 1 ? <Crown className="h-3.5 w-3.5" /> : e.rank}
              </span>
              <span className="min-w-0 flex-1 truncate font-medium">
                {e.nickname || 'Player'}
                {mine && <span className="ml-1.5 text-xs text-primary">(you)</span>}
              </span>
              <span className="shrink-0 font-mono tabular-nums">{e.score.toLocaleString()}</span>
            </motion.li>
          );
        })}
      </AnimatePresence>
    </ol>
  );
}
