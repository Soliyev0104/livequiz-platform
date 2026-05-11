import { QueryClient } from '@tanstack/react-query';

export function makeQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        retry: 1,
        refetchOnWindowFocus: false,
        // Quiz lists and similar resources stay fresh for 30s; live-match
        // pages do their own thing via the WebSocket store.
        staleTime: 30_000,
      },
      mutations: {
        retry: 0,
      },
    },
  });
}
