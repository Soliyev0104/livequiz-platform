'use client';

import { useQuery } from '@tanstack/react-query';

import { api } from '@/lib/api-client';

export function useMyQuizSets(ownerId: string | undefined) {
  return useQuery({
    queryKey: ['quiz-sets', 'mine', ownerId],
    queryFn: () => api.quizSets.listMine(ownerId as string),
    enabled: !!ownerId,
    staleTime: 30_000,
  });
}
