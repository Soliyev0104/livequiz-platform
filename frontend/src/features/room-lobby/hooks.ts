'use client';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api } from '@/lib/api-client';
import type { RoomCreate } from '@/lib/types';

export function useCreateRoom() {
  return useMutation({
    mutationFn: (body: RoomCreate) => api.rooms.create(body),
  });
}

export function useRoomSnapshot(code: string, enabled = true) {
  return useQuery({
    queryKey: ['room', code],
    queryFn: () => api.rooms.get(code),
    enabled: enabled && !!code,
    refetchOnWindowFocus: false,
    staleTime: 0,
  });
}

export function useStartMatch(code: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.rooms.start(code),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['room', code] }),
  });
}

export function usePauseMatch(code: string) {
  return useMutation({ mutationFn: () => api.rooms.pause(code) });
}

export function useResumeMatch(code: string) {
  return useMutation({ mutationFn: () => api.rooms.resume(code) });
}

export function useEndMatch(code: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.rooms.end(code),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['room', code] }),
  });
}
