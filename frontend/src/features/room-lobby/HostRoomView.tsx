'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { BarChart3, Trophy } from 'lucide-react';
import * as React from 'react';
import { toast } from 'sonner';

import { AppShell } from '@/components/AppShell';
import { AuthGuard } from '@/components/AuthGuard';
import { ReconnectOverlay } from '@/components/ReconnectOverlay';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Leaderboard } from '@/features/live-match/Leaderboard';
import { QuestionDisplay } from '@/features/live-match/QuestionDisplay';
import { TimerBar } from '@/features/live-match/TimerBar';
import {
  useClockSkew,
  useClosedQuestion,
  useConnection,
  useCurrentQuestion,
  useFinished,
  useLeaderboard,
  useMatchInfo,
  usePhase,
  usePlayerCount,
  useRoom,
} from '@/features/live-match/store';
import { useLiveSocket } from '@/features/live-match/useLiveSocket';
import { HostMatchControls } from '@/features/room-lobby/HostMatchControls';
import { ParticipantList } from '@/features/room-lobby/ParticipantList';
import { RoomCodeCard } from '@/features/room-lobby/RoomCodeCard';
import { loadHostRoomSession, type HostRoomSession } from '@/features/room-lobby/host-session';
import { resolveWsUrl } from '@/lib/ws-client';

function HostRoomInner({ code }: { code: string }): React.JSX.Element {
  const router = useRouter();
  const [session, setSession] = React.useState<HostRoomSession | 'loading' | 'missing'>('loading');

  React.useEffect(() => {
    const s = loadHostRoomSession(code);
    if (!s) {
      toast.error('Open this room from your dashboard to host it.');
      setSession('missing');
      router.replace('/dashboard');
      return;
    }
    setSession(s);
  }, [code, router]);

  const wsUrl =
    typeof session === 'object' ? resolveWsUrl({ relativeUrl: session.hostWsUrl }) : null;
  useLiveSocket({ code, wsUrl });

  const phase = usePhase();
  const connection = useConnection();
  const currentQuestion = useCurrentQuestion();
  const closedQuestion = useClosedQuestion();
  const leaderboard = useLeaderboard();
  const matchInfo = useMatchInfo();
  const playerCount = usePlayerCount();
  const finished = useFinished();
  const skew = useClockSkew();
  const room = useRoom();

  if (session === 'loading' || session === 'missing') {
    return <div className="p-16 text-center text-muted-foreground">Loading room…</div>;
  }

  const matchStatus = finished ? 'completed' : matchInfo?.status ?? null;
  const inLobby = phase === 'lobby' && !finished;
  const reconnecting = connection === 'reconnecting' || connection === 'closed';

  return (
    <div className="relative mx-auto w-full max-w-6xl px-4 py-6 sm:px-6">
      <ReconnectOverlay active={reconnecting} />

      <header className="mb-6 flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="text-sm text-muted-foreground">Hosting</p>
          <h1 className="text-2xl font-semibold leading-tight">{session.quizTitle}</h1>
        </div>
        <div className="flex items-center gap-2">
          <Badge variant="outline">{playerCount} players</Badge>
          {matchInfo && (
            <Badge variant={matchStatus === 'paused' ? 'muted' : 'success'} className="capitalize">
              {matchStatus}
            </Badge>
          )}
        </div>
      </header>

      {finished ? (
        <div className="grid gap-6 lg:grid-cols-[1fr_320px]">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Trophy className="h-5 w-5 text-amber-400" /> Final leaderboard
              </CardTitle>
            </CardHeader>
            <CardContent>
              <Leaderboard entries={leaderboard.top} emptyHint="No scores recorded." />
            </CardContent>
          </Card>
          <div className="space-y-4">
            <Card>
              <CardContent className="space-y-3 p-6">
                <p className="text-sm text-muted-foreground">The match is complete.</p>
                <Button asChild className="w-full">
                  <Link href={`/matches/${finished.match_id}/analytics`} className="gap-1.5">
                    <BarChart3 className="h-4 w-4" /> View analytics
                  </Link>
                </Button>
                <Button asChild variant="outline" className="w-full">
                  <Link href="/dashboard">Back to dashboard</Link>
                </Button>
              </CardContent>
            </Card>
            <ParticipantList />
          </div>
        </div>
      ) : inLobby ? (
        <div className="grid gap-6 lg:grid-cols-[1fr_340px]">
          <div className="space-y-6">
            <RoomCodeCard code={code} />
            <ParticipantList />
          </div>
          <div className="space-y-6">
            <Card>
              <CardHeader>
                <CardTitle className="text-base">Start the match</CardTitle>
              </CardHeader>
              <CardContent className="space-y-3">
                <HostMatchControls code={code} matchStatus="lobby" canStart={playerCount >= 1} />
                {playerCount < 1 && (
                  <p className="text-xs text-muted-foreground">Waiting for at least one player to join.</p>
                )}
              </CardContent>
            </Card>
            <div className="rounded-lg border border-dashed border-border/70 p-4 text-sm text-muted-foreground">
              Share the room code or QR with players. Questions advance automatically once the match starts.
            </div>
          </div>
        </div>
      ) : (
        <div className="grid gap-6 lg:grid-cols-[1fr_320px]">
          <div className="space-y-4">
            {currentQuestion ? (
              <>
                <TimerBar
                  startedAt={currentQuestion.started_at}
                  deadlineAt={currentQuestion.deadline_at}
                  skewMs={skew}
                  closed={phase === 'closed'}
                />
                <QuestionDisplay question={currentQuestion} closed={phase === 'closed' ? closedQuestion : null} />
                {currentQuestion && (
                  <p className="text-sm text-muted-foreground">
                    Question {currentQuestion.position}
                    {matchInfo?.questionCount ? ` of ${matchInfo.questionCount}` : ''}
                  </p>
                )}
              </>
            ) : (
              <Card>
                <CardContent className="p-10 text-center text-muted-foreground">
                  {matchStatus === 'paused' ? 'Match paused.' : 'Starting the match…'}
                </CardContent>
              </Card>
            )}
          </div>
          <div className="space-y-4">
            <Card>
              <CardHeader>
                <CardTitle className="text-base">Match controls</CardTitle>
              </CardHeader>
              <CardContent>
                <HostMatchControls code={code} matchStatus={matchStatus} canStart={false} />
              </CardContent>
            </Card>
            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="text-base">Leaderboard</CardTitle>
              </CardHeader>
              <CardContent>
                <Leaderboard entries={leaderboard.top} emptyHint="Waiting for answers…" />
              </CardContent>
            </Card>
            <ParticipantList />
          </div>
        </div>
      )}
    </div>
  );
}

export function HostRoomView({ code }: { code: string }): React.JSX.Element {
  return (
    <AuthGuard requireRole={['host', 'admin']}>
      <AppShell>
        <HostRoomInner code={code.toUpperCase()} />
      </AppShell>
    </AuthGuard>
  );
}
