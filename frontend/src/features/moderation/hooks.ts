'use client';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api } from '@/lib/api-client';
import type { DecisionRequest, ReportStatus } from '@/lib/types';

export function useReports(status: ReportStatus) {
  return useQuery({
    queryKey: ['moderation', 'reports', status],
    queryFn: () => api.moderation.listReports({ status, limit: 100 }),
    staleTime: 15_000,
  });
}

export function useDecideReport() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ reportId, body }: { reportId: string; body: DecisionRequest }) =>
      api.moderation.decide(reportId, body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['moderation', 'reports'] }),
  });
}
