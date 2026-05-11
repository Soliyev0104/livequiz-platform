'use client';

import { useQuery } from '@tanstack/react-query';

import { api } from '@/lib/api-client';

export function useMatchAnalytics(matchId: string) {
  return useQuery({
    queryKey: ['match-analytics', matchId],
    queryFn: () => api.matches.analytics(matchId),
    enabled: !!matchId,
    retry: 1,
    staleTime: 60_000,
  });
}
