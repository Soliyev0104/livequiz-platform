'use client';

import { motion } from 'framer-motion';
import { Loader2 } from 'lucide-react';
import * as React from 'react';

import { Card, CardContent } from '@/components/ui/card';
import { usePlayerCount } from '@/features/live-match/store';

export function LobbyWaiting({
  code,
  nickname,
  starting,
}: {
  code: string;
  nickname: string;
  starting?: boolean;
}): React.JSX.Element {
  const playerCount = usePlayerCount();
  return (
    <Card className="mx-auto max-w-lg">
      <CardContent className="flex flex-col items-center gap-4 p-10 text-center">
        <motion.div
          animate={{ scale: [1, 1.06, 1] }}
          transition={{ repeat: Infinity, duration: 1.8 }}
          className="grid h-16 w-16 place-items-center rounded-full bg-primary/15 text-primary"
        >
          <Loader2 className="h-7 w-7 animate-spin" />
        </motion.div>
        <div>
          <h1 className="text-2xl font-semibold">
            {starting ? 'Get ready…' : "You're in!"}
          </h1>
          <p className="mt-1 text-muted-foreground">
            {starting
              ? 'The host is starting the match.'
              : 'Waiting for the host to start the match.'}
          </p>
        </div>
        <div className="flex items-center gap-4 text-sm text-muted-foreground">
          <span>
            Room <span className="font-mono font-semibold tracking-widest text-foreground">{code}</span>
          </span>
          <span>·</span>
          <span>
            Playing as <span className="font-medium text-foreground">{nickname}</span>
          </span>
          <span>·</span>
          <span>{playerCount} players</span>
        </div>
      </CardContent>
    </Card>
  );
}
