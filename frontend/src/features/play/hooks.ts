'use client';

import { useMutation } from '@tanstack/react-query';

import { api } from '@/lib/api-client';
import { useAuthStore } from '@/lib/auth';
import type { AnswerSubmitRequest, RoomJoinRequest } from '@/lib/types';

export function useJoinRoom() {
  return useMutation({
    mutationFn: ({ code, body }: { code: string; body: RoomJoinRequest }) => {
      const accessToken = useAuthStore.getState().accessToken ?? undefined;
      return api.rooms.join(code, body, accessToken);
    },
  });
}

export function useSubmitAnswerRest(matchId: string, participantToken: string) {
  return useMutation({
    mutationFn: ({ body, requestId }: { body: AnswerSubmitRequest; requestId?: string }) =>
      api.matches.submitAnswer(matchId, body, participantToken, requestId),
  });
}
