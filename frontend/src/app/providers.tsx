'use client';

import { QueryClientProvider } from '@tanstack/react-query';
import { ThemeProvider } from 'next-themes';
import * as React from 'react';

import { TooltipProvider } from '@/components/ui/tooltip';
import { Toaster } from '@/components/ui/sonner';
import { AuthHydrator } from '@/components/AuthHydrator';
import { makeQueryClient } from '@/lib/query-client';

export function Providers({ children }: { children: React.ReactNode }): React.JSX.Element {
  const [queryClient] = React.useState(() => makeQueryClient());

  return (
    <QueryClientProvider client={queryClient}>
      <ThemeProvider
        attribute="class"
        defaultTheme="dark"
        enableSystem={false}
        disableTransitionOnChange
      >
        <TooltipProvider delayDuration={200}>
          <AuthHydrator />
          {children}
          <Toaster />
        </TooltipProvider>
      </ThemeProvider>
    </QueryClientProvider>
  );
}
