'use client';

import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
import * as React from 'react';

import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { useAuthStore } from '@/lib/auth';
import type { Role } from '@/lib/types';

interface AuthGuardProps {
  children: React.ReactNode;
  /** Restrict to these roles. Pass `['host', 'admin']` etc. — admin is not
   * implicitly granted unless listed. */
  requireRole?: Role[];
}

export function AuthGuard({ children, requireRole }: AuthGuardProps): React.JSX.Element {
  const router = useRouter();
  const pathname = usePathname();
  const status = useAuthStore((s) => s.status);
  const user = useAuthStore((s) => s.user);

  React.useEffect(() => {
    if (status === 'anon') {
      const next = encodeURIComponent(pathname || '/dashboard');
      router.replace(`/login?next=${next}`);
    }
  }, [status, pathname, router]);

  if (status === 'idle' || status === 'loading') {
    return (
      <div className="mx-auto w-full max-w-5xl space-y-4 p-8">
        <Skeleton className="h-10 w-64" />
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {Array.from({ length: 6 }).map((_, i) => (
            <Skeleton key={i} className="h-32 w-full" />
          ))}
        </div>
      </div>
    );
  }

  if (status === 'anon') {
    return (
      <div className="flex min-h-[60vh] items-center justify-center">
        <Skeleton className="h-8 w-48" />
      </div>
    );
  }

  if (requireRole && (!user || !requireRole.includes(user.role))) {
    return (
      <div className="flex min-h-[60vh] flex-col items-center justify-center gap-4 p-8 text-center">
        <p className="text-sm font-medium uppercase tracking-widest text-muted-foreground">403</p>
        <h1 className="text-2xl font-semibold">You do not have access to this page</h1>
        <p className="max-w-md text-muted-foreground">
          This area requires the {requireRole.join(' or ')} role.
        </p>
        <Button asChild variant="outline">
          <Link href="/dashboard">Back to dashboard</Link>
        </Button>
      </div>
    );
  }

  return <>{children}</>;
}
