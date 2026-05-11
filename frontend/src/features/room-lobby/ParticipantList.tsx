'use client';

import { AnimatePresence, motion } from 'framer-motion';
import { Users } from 'lucide-react';
import * as React from 'react';

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { useParticipants, usePlayerCount } from '@/features/live-match/store';
import { cn } from '@/lib/utils';

function initials(name: string): string {
  return (
    name
      .split(/\s+/)
      .filter(Boolean)
      .slice(0, 2)
      .map((p) => p[0]?.toUpperCase() ?? '')
      .join('') || '?'
  );
}

export function ParticipantList(): React.JSX.Element {
  const participants = useParticipants();
  const playerCount = usePlayerCount();

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-3">
        <CardTitle className="flex items-center gap-2 text-base">
          <Users className="h-4 w-4" /> Players
        </CardTitle>
        <span className="rounded-full bg-muted px-2.5 py-0.5 text-sm font-medium">{playerCount}</span>
      </CardHeader>
      <CardContent>
        {participants.length === 0 ? (
          <p className="text-sm text-muted-foreground">Waiting for players to join…</p>
        ) : (
          <ul className="flex flex-wrap gap-2">
            <AnimatePresence initial={false}>
              {participants.map((p) => (
                <motion.li
                  key={p.participant_id}
                  layout
                  initial={{ opacity: 0, scale: 0.85 }}
                  animate={{ opacity: 1, scale: 1 }}
                  exit={{ opacity: 0, scale: 0.85 }}
                  transition={{ type: 'spring', stiffness: 500, damping: 30 }}
                  className={cn(
                    'flex items-center gap-2 rounded-full border px-3 py-1.5 text-sm',
                    p.online ? 'border-border bg-card' : 'border-border/50 bg-muted/40 text-muted-foreground',
                  )}
                >
                  <span className="grid h-6 w-6 place-items-center rounded-full bg-primary/15 text-xs font-medium text-primary">
                    {initials(p.nickname)}
                  </span>
                  <span className="max-w-[10rem] truncate">{p.nickname}</span>
                </motion.li>
              ))}
            </AnimatePresence>
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
