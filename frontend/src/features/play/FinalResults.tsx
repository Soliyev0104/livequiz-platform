'use client';

import confetti from 'canvas-confetti';
import Link from 'next/link';
import { Trophy } from 'lucide-react';
import * as React from 'react';

import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Leaderboard } from '@/features/live-match/Leaderboard';
import type { LeaderboardEntry } from '@/lib/types';
import { ordinal } from '@/lib/utils';

export function FinalResults({
  leaderboard,
  participantId,
  nickname,
}: {
  leaderboard: LeaderboardEntry[];
  participantId: string;
  nickname: string;
}): React.JSX.Element {
  const myEntry = leaderboard.find((e) => e.participant_id === participantId) ?? null;
  const isWinner = myEntry?.rank === 1;

  React.useEffect(() => {
    if (!isWinner) return;
    const end = Date.now() + 1200;
    const tick = (): void => {
      confetti({ particleCount: 40, spread: 70, origin: { y: 0.6 }, startVelocity: 45 });
      if (Date.now() < end) requestAnimationFrame(tick);
    };
    tick();
  }, [isWinner]);

  return (
    <div className="mx-auto w-full max-w-2xl space-y-6">
      <Card className="overflow-hidden">
        <CardContent className="flex flex-col items-center gap-3 p-8 text-center">
          <div className="grid h-16 w-16 place-items-center rounded-full bg-amber-400/20 text-amber-400">
            <Trophy className="h-8 w-8" />
          </div>
          <h1 className="text-3xl font-semibold">
            {isWinner ? 'You won!' : myEntry ? `You finished ${ordinal(myEntry.rank)}` : 'Match complete'}
          </h1>
          <p className="text-muted-foreground">
            {myEntry
              ? `${nickname} · ${myEntry.score.toLocaleString()} points`
              : 'Thanks for playing.'}
          </p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">Final leaderboard</CardTitle>
        </CardHeader>
        <CardContent>
          <Leaderboard
            entries={leaderboard}
            highlightParticipantId={participantId}
            emptyHint="No scores recorded."
          />
        </CardContent>
      </Card>

      <div className="flex justify-center gap-3">
        <Button asChild variant="outline">
          <Link href="/join">Join another room</Link>
        </Button>
        <Button asChild>
          <Link href="/">Back home</Link>
        </Button>
      </div>
    </div>
  );
}
