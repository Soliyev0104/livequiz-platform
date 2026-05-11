'use client';

import { useRouter } from 'next/navigation';
import * as React from 'react';
import { toast } from 'sonner';

import { ReconnectOverlay } from '@/components/ReconnectOverlay';
import { Logo } from '@/components/Logo';
import { ThemeToggle } from '@/components/ThemeToggle';
import { BetweenLeaderboard } from '@/features/play/BetweenLeaderboard';
import { FinalResults } from '@/features/play/FinalResults';
import { LobbyWaiting } from '@/features/play/LobbyWaiting';
import { PlayerQuestionScreen } from '@/features/play/PlayerQuestionScreen';
import { loadPlayerRoomSession, type PlayerRoomSession } from '@/features/play/player-session';
import {
  useClockSkew,
  useClosedQuestion,
  useConnection,
  useCurrentQuestion,
  useFinished,
  useLeaderboard,
  useLiveMatchStore,
  useMatchInfo,
  useMyAnswer,
  usePhase,
} from '@/features/live-match/store';
import { useLiveSocket } from '@/features/live-match/useLiveSocket';
import { remainingMs } from '@/lib/clock';
import { api } from '@/lib/api-client';
import { newRequestId } from '@/lib/utils';
import { resolveWsUrl } from '@/lib/ws-client';
import type { LeaderboardEntry } from '@/lib/types';

function PlayInner({ code }: { code: string }): React.JSX.Element {
  const router = useRouter();
  const [session, setSession] = React.useState<PlayerRoomSession | 'loading' | 'missing'>('loading');

  React.useEffect(() => {
    const s = loadPlayerRoomSession(code);
    if (!s) {
      setSession('missing');
      router.replace(`/join?code=${encodeURIComponent(code)}`);
      return;
    }
    setSession(s);
  }, [code, router]);

  const wsUrl = typeof session === 'object' ? resolveWsUrl({ relativeUrl: session.wsUrl }) : null;
  const socket = useLiveSocket({ code, wsUrl });

  const phase = usePhase();
  const connection = useConnection();
  const currentQuestion = useCurrentQuestion();
  const closedQuestion = useClosedQuestion();
  const myAnswer = useMyAnswer();
  const leaderboard = useLeaderboard();
  const matchInfo = useMatchInfo();
  const finished = useFinished();
  const skew = useClockSkew();

  const participantId = typeof session === 'object' ? session.participantId : '';
  const participantToken = typeof session === 'object' ? session.participantToken : '';
  const nickname = typeof session === 'object' ? session.nickname : '';

  // Re-tick so the "deadline missed" overlay flips on time.
  const [, force] = React.useReducer((n: number) => n + 1, 0);
  React.useEffect(() => {
    if (connection !== 'reconnecting' && connection !== 'closed') return;
    const id = setInterval(force, 500);
    return () => clearInterval(id);
  }, [connection]);

  const submitAnswer = React.useCallback(
    async (selectedOptionIds: string[]) => {
      const store = useLiveMatchStore.getState();
      const cq = store.currentQuestion;
      const matchId = store.match?.matchId;
      if (!cq || !matchId) return;
      if (store.myAnswer?.matchQuestionId === cq.match_question_id) return; // already answered
      store.markAnswerSubmitted(cq.match_question_id, selectedOptionIds);
      const clientSentAt = new Date().toISOString();
      if (socket?.isOpen) {
        socket.send('answer.submit', {
          match_id: matchId,
          match_question_id: cq.match_question_id,
          selected_option_ids: selectedOptionIds,
          client_sent_at: clientSentAt,
        });
        return;
      }
      // REST fallback when the socket is down.
      try {
        const res = await api.matches.submitAnswer(
          matchId,
          {
            match_question_id: cq.match_question_id,
            selected_option_ids: selectedOptionIds,
            client_sent_at: clientSentAt,
          },
          participantToken,
          newRequestId(),
        );
        useLiveMatchStore.getState().applyAnswerAccepted({
          submission_id: res.submission_id,
          accepted: res.accepted,
          score_awarded: res.score_awarded,
          response_time_ms: res.response_time_ms,
        });
      } catch (err) {
        const code2 = (err as { code?: string }).code;
        if (code2 === 'QUESTION_CLOSED') {
          useLiveMatchStore.getState().setError({ code: 'QUESTION_CLOSED', message: null, retry_after_ms: null });
        } else {
          toast.error('Could not submit your answer.');
        }
      }
    },
    [socket, participantToken],
  );

  // Fetch the full final leaderboard once the match finishes.
  const [finalBoard, setFinalBoard] = React.useState<LeaderboardEntry[] | null>(null);
  React.useEffect(() => {
    if (!finished || !matchInfo?.matchId || !participantToken) return;
    let cancelled = false;
    api.matches
      .leaderboard(matchInfo.matchId, participantToken, 100)
      .then((res) => {
        if (!cancelled) setFinalBoard(res.entries);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [finished, matchInfo?.matchId, participantToken]);

  if (session === 'loading' || session === 'missing') {
    return <div className="p-16 text-center text-muted-foreground">Loading…</div>;
  }

  const reconnecting = connection === 'reconnecting' || connection === 'closed';
  const answeredCurrent = !!myAnswer && myAnswer.matchQuestionId === currentQuestion?.match_question_id;
  const deadlineMissed =
    reconnecting &&
    phase === 'question' &&
    !!currentQuestion &&
    !answeredCurrent &&
    remainingMs(currentQuestion.deadline_at, skew) <= 0;

  return (
    <div className="relative flex min-h-screen flex-col">
      <ReconnectOverlay active={reconnecting} deadlineMissed={deadlineMissed} />
      <header className="flex items-center justify-between border-b border-border/70 px-4 py-3 sm:px-6">
        <Logo href="/" />
        <div className="flex items-center gap-3 text-sm text-muted-foreground">
          <span>
            Room <span className="font-mono font-semibold tracking-widest text-foreground">{code}</span>
          </span>
          <ThemeToggle />
        </div>
      </header>

      <main className="flex flex-1 items-center justify-center px-4 py-8 sm:px-6">
        {phase === 'finished' ? (
          <FinalResults
            leaderboard={finalBoard ?? leaderboard.top}
            participantId={participantId}
            nickname={nickname}
          />
        ) : phase === 'closed' && currentQuestion && closedQuestion ? (
          <BetweenLeaderboard
            question={currentQuestion}
            closed={closedQuestion}
            myAnswer={myAnswer}
            leaderboard={leaderboard.top}
            participantId={participantId}
          />
        ) : phase === 'question' && currentQuestion ? (
          <PlayerQuestionScreen
            question={currentQuestion}
            myAnswer={myAnswer}
            skewMs={skew}
            questionCount={matchInfo?.questionCount}
            onSubmit={submitAnswer}
          />
        ) : (
          <LobbyWaiting code={code} nickname={nickname} starting={phase === 'starting'} />
        )}
      </main>
    </div>
  );
}

export function PlayView({ code }: { code: string }): React.JSX.Element {
  return <PlayInner code={code.toUpperCase()} />;
}
