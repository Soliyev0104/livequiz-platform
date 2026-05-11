'use client';

import * as React from 'react';

import { api } from '@/lib/api-client';
import { LiveSocket } from '@/lib/ws-client';
import type { ServerMessage } from '@/lib/types';
import { useLiveMatchStore } from '@/features/live-match/store';

interface UseLiveSocketArgs {
  code: string;
  wsUrl: string | null;
}

function dispatch(msg: ServerMessage): void {
  const store = useLiveMatchStore.getState();
  switch (msg.type) {
    case 'room.snapshot':
      store.applySnapshot(msg.payload);
      break;
    case 'participant.joined':
      store.applyParticipantJoined(msg.payload);
      break;
    case 'participant.left':
      store.applyParticipantLeft(msg.payload);
      break;
    case 'match.started':
      store.applyMatchStarted(msg.payload);
      break;
    case 'question.started':
      store.applyQuestionStarted(msg.payload);
      break;
    case 'answer.accepted':
      store.applyAnswerAccepted(msg.payload);
      break;
    case 'leaderboard.updated':
      store.applyLeaderboardUpdated(msg.payload);
      break;
    case 'question.closed':
      store.applyQuestionClosed(msg.payload);
      break;
    case 'match.finished':
      store.applyMatchFinished(msg.payload);
      break;
    case 'error':
      store.setError(msg.payload);
      break;
    case 'room.heartbeat.ack':
      // server clock echo; nothing to store beyond skew which we lock on snapshot
      break;
    default:
      break;
  }
}

export function useLiveSocket({ code, wsUrl }: UseLiveSocketArgs): LiveSocket | null {
  const [socket, setSocket] = React.useState<LiveSocket | null>(null);

  React.useEffect(() => {
    if (!wsUrl) return;
    useLiveMatchStore.getState().reset(code);
    const ls = new LiveSocket(wsUrl, {
      onOpen: () => useLiveMatchStore.getState().setConnection('open'),
      onMessage: dispatch,
      onClose: ({ willReconnect }) =>
        useLiveMatchStore.getState().setConnection(willReconnect ? 'reconnecting' : 'closed'),
      onReconnect: () => {
        // Belt and braces: the server re-pushes room.snapshot on connect, but
        // we also re-fetch the REST snapshot in case any message was missed.
        void api.rooms
          .get(code)
          .then((snap) => useLiveMatchStore.getState().applySnapshot(snap))
          .catch(() => undefined);
      },
      onError: () => undefined,
    });
    setSocket(ls);
    ls.connect();
    return () => {
      ls.close();
      setSocket(null);
    };
  }, [code, wsUrl]);

  return socket;
}
