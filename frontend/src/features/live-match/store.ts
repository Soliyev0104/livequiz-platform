'use client';

// Zustand store for one live room. The WebSocket `room.snapshot` *replaces*
// state; every other message is a patch over the last snapshot. Components
// read through atomic selector hooks so that, e.g., the player's question
// screen does not re-render when only the leaderboard changes.

import { create } from 'zustand';

import { computeSkewMs } from '@/lib/clock';
import type {
  AnswerAcceptedPayload,
  LeaderboardEntry,
  LeaderboardUpdatedPayload,
  MatchFinishedPayload,
  MatchStartedPayload,
  ParticipantJoinedPayload,
  ParticipantLeftPayload,
  QuestionClosedPayload,
  QuestionStartedPayload,
  RoomSnapshotMatch,
  RoomSnapshotParticipant,
  RoomSnapshotPayload,
  RoomSnapshotRoom,
  RoomStatus,
  WsErrorPayload,
} from '@/lib/types';

export type LiveConnection = 'idle' | 'connecting' | 'open' | 'reconnecting' | 'closed';
export type LivePhase = 'lobby' | 'starting' | 'question' | 'closed' | 'finished';

export interface MyAnswer {
  matchQuestionId: string;
  selectedOptionIds: string[];
  pending: boolean;
  accepted: boolean;
  tooLate: boolean;
  submissionId?: string;
  scoreAwarded?: number;
  responseTimeMs?: number;
}

interface MatchInfo {
  matchId: string;
  questionCount: number;
  status: string;
}

interface LiveMatchState {
  roomCode: string | null;
  connection: LiveConnection;
  room: RoomSnapshotRoom | null;
  participants: RoomSnapshotParticipant[];
  playerCount: number;
  match: MatchInfo | null;
  currentQuestion: QuestionStartedPayload | null;
  closedQuestion: QuestionClosedPayload | null;
  leaderboard: { version: number; top: LeaderboardEntry[] };
  myAnswer: MyAnswer | null;
  clockSkewMs: number;
  skewLocked: boolean;
  finished: MatchFinishedPayload | null;
  lastError: WsErrorPayload | null;

  reset: (code: string) => void;
  setConnection: (c: LiveConnection) => void;
  applySnapshot: (p: RoomSnapshotPayload) => void;
  applyParticipantJoined: (p: ParticipantJoinedPayload) => void;
  applyParticipantLeft: (p: ParticipantLeftPayload) => void;
  applyMatchStarted: (p: MatchStartedPayload) => void;
  applyQuestionStarted: (p: QuestionStartedPayload) => void;
  applyAnswerAccepted: (p: AnswerAcceptedPayload) => void;
  applyLeaderboardUpdated: (p: LeaderboardUpdatedPayload) => void;
  applyQuestionClosed: (p: QuestionClosedPayload) => void;
  applyMatchFinished: (p: MatchFinishedPayload) => void;
  setError: (p: WsErrorPayload) => void;
  markAnswerSubmitted: (matchQuestionId: string, selectedOptionIds: string[]) => void;
}

function emptyState(): Omit<
  LiveMatchState,
  | 'reset'
  | 'setConnection'
  | 'applySnapshot'
  | 'applyParticipantJoined'
  | 'applyParticipantLeft'
  | 'applyMatchStarted'
  | 'applyQuestionStarted'
  | 'applyAnswerAccepted'
  | 'applyLeaderboardUpdated'
  | 'applyQuestionClosed'
  | 'applyMatchFinished'
  | 'setError'
  | 'markAnswerSubmitted'
> {
  return {
    roomCode: null,
    connection: 'idle',
    room: null,
    participants: [],
    playerCount: 0,
    match: null,
    currentQuestion: null,
    closedQuestion: null,
    leaderboard: { version: -1, top: [] },
    myAnswer: null,
    clockSkewMs: 0,
    skewLocked: false,
    finished: null,
    lastError: null,
  };
}

function maybeLockSkew(state: LiveMatchState, serverNowIso?: string): Partial<LiveMatchState> {
  if (state.skewLocked || !serverNowIso) return {};
  return { clockSkewMs: computeSkewMs(serverNowIso), skewLocked: true };
}

function matchFromSnapshot(m: RoomSnapshotMatch | null): MatchInfo | null {
  if (!m) return null;
  return {
    matchId: m.match_id,
    questionCount: typeof m.question_count === 'number' ? m.question_count : 0,
    status: typeof m.status === 'string' ? m.status : 'running',
  };
}

export const useLiveMatchStore = create<LiveMatchState>((set, get) => ({
  ...emptyState(),

  reset(code) {
    set({ ...emptyState(), roomCode: code, connection: 'connecting' });
  },

  setConnection(c) {
    set({ connection: c });
  },

  applySnapshot(p) {
    const current = get();
    const cq = (p.match?.current_question as QuestionStartedPayload | null | undefined) ?? null;
    set({
      room: p.room,
      participants: p.participants ?? [],
      playerCount: p.room?.player_count ?? p.participants?.length ?? 0,
      match: matchFromSnapshot(p.match),
      currentQuestion: cq ?? current.currentQuestion,
      leaderboard:
        p.leaderboard && p.leaderboard.length
          ? { version: Math.max(0, current.leaderboard.version), top: p.leaderboard }
          : current.leaderboard,
      ...maybeLockSkew(current, cq?.server_now),
    });
  },

  applyParticipantJoined(p) {
    set((s) => {
      const exists = s.participants.some((x) => x.participant_id === p.participant_id);
      const participants = exists
        ? s.participants.map((x) =>
            x.participant_id === p.participant_id ? { ...x, online: true, nickname: p.nickname } : x,
          )
        : [...s.participants, { participant_id: p.participant_id, nickname: p.nickname, online: true }];
      return { participants, playerCount: p.player_count };
    });
  },

  applyParticipantLeft(p) {
    set((s) => ({
      participants: s.participants.map((x) =>
        x.participant_id === p.participant_id ? { ...x, online: false } : x,
      ),
      playerCount: p.player_count,
    }));
  },

  applyMatchStarted(p) {
    set((s) => ({
      match: { matchId: p.match_id, questionCount: p.question_count, status: 'running' },
      room: s.room ? { ...s.room, status: 'running' as RoomStatus } : s.room,
      finished: null,
      closedQuestion: null,
      currentQuestion: null,
      myAnswer: null,
      ...maybeLockSkew(s, p.server_now),
    }));
  },

  applyQuestionStarted(p) {
    set((s) => ({
      currentQuestion: p,
      closedQuestion: null,
      myAnswer: null,
      lastError: null,
      ...maybeLockSkew(s, p.server_now),
    }));
  },

  applyAnswerAccepted(p) {
    set((s) => ({
      myAnswer: {
        matchQuestionId: s.currentQuestion?.match_question_id ?? s.myAnswer?.matchQuestionId ?? '',
        selectedOptionIds: s.myAnswer?.selectedOptionIds ?? [],
        pending: false,
        accepted: p.accepted,
        tooLate: false,
        submissionId: p.submission_id,
        scoreAwarded: p.score_awarded,
        responseTimeMs: p.response_time_ms,
      },
    }));
  },

  applyLeaderboardUpdated(p) {
    set((s) => (p.version >= s.leaderboard.version ? { leaderboard: { version: p.version, top: p.top } } : {}));
  },

  applyQuestionClosed(p) {
    set({ closedQuestion: p });
  },

  applyMatchFinished(p) {
    set((s) => ({
      finished: p,
      match: s.match ? { ...s.match, status: 'completed' } : s.match,
      room: s.room ? { ...s.room, status: 'completed' as RoomStatus } : s.room,
    }));
  },

  setError(p) {
    set((s) => {
      // Any error that arrives while an answer is in flight means the
      // submission did not land — stop showing "waiting for the server".
      if (s.myAnswer?.pending) {
        const tooLate = p.code === 'QUESTION_CLOSED';
        return { lastError: p, myAnswer: { ...s.myAnswer, pending: false, tooLate } };
      }
      return { lastError: p };
    });
  },

  markAnswerSubmitted(matchQuestionId, selectedOptionIds) {
    set({
      myAnswer: { matchQuestionId, selectedOptionIds, pending: true, accepted: false, tooLate: false },
    });
  },
}));

// --- derived ---------------------------------------------------------------

export function derivePhase(s: LiveMatchState): LivePhase {
  if (s.finished) return 'finished';
  if (s.closedQuestion && s.currentQuestion && s.closedQuestion.match_question_id === s.currentQuestion.match_question_id) {
    return 'closed';
  }
  if (s.currentQuestion) return 'question';
  if (s.match && (s.match.status === 'running' || s.match.status === 'paused')) return 'starting';
  return 'lobby';
}

// --- atomic selector hooks (memoized by Zustand's referential checks) -------

export const usePhase = (): LivePhase => useLiveMatchStore(derivePhase);
export const useConnection = (): LiveConnection => useLiveMatchStore((s) => s.connection);
export const useRoom = (): RoomSnapshotRoom | null => useLiveMatchStore((s) => s.room);
export const useParticipants = (): RoomSnapshotParticipant[] => useLiveMatchStore((s) => s.participants);
export const usePlayerCount = (): number => useLiveMatchStore((s) => s.playerCount);
export const useMatchInfo = (): MatchInfo | null => useLiveMatchStore((s) => s.match);
export const useCurrentQuestion = (): QuestionStartedPayload | null =>
  useLiveMatchStore((s) => s.currentQuestion);
export const useClosedQuestion = (): QuestionClosedPayload | null =>
  useLiveMatchStore((s) => s.closedQuestion);
export const useLeaderboard = (): { version: number; top: LeaderboardEntry[] } =>
  useLiveMatchStore((s) => s.leaderboard);
export const useMyAnswer = (): MyAnswer | null => useLiveMatchStore((s) => s.myAnswer);
export const useClockSkew = (): number => useLiveMatchStore((s) => s.clockSkewMs);
export const useFinished = (): MatchFinishedPayload | null => useLiveMatchStore((s) => s.finished);
