'use client';

import * as React from 'react';

import { useAuthStore } from '@/lib/auth';

/** Restores the session once on mount by exchanging the httpOnly refresh
 * cookie for a fresh access token (via the auth BFF). Renders nothing. */
export function AuthHydrator(): null {
  const hydrate = useAuthStore((s) => s.hydrate);
  React.useEffect(() => {
    void hydrate();
  }, [hydrate]);
  return null;
}
