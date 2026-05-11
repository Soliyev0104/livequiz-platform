'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { LogOut, ShieldCheck } from 'lucide-react';
import * as React from 'react';

import { Logo } from '@/components/Logo';
import { ThemeToggle } from '@/components/ThemeToggle';
import { Avatar, AvatarFallback } from '@/components/ui/avatar';
import { Button } from '@/components/ui/button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { hasRole, useAuthStore } from '@/lib/auth';

function initials(name: string): string {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((p) => p[0]?.toUpperCase() ?? '')
    .join('') || '?';
}

export function TopBar(): React.JSX.Element {
  const router = useRouter();
  const status = useAuthStore((s) => s.status);
  const user = useAuthStore((s) => s.user);
  const logout = useAuthStore((s) => s.logout);

  const authed = status === 'authed' && !!user;

  return (
    <header className="sticky top-0 z-40 border-b border-border/80 bg-background/80 backdrop-blur">
      <div className="mx-auto flex h-16 max-w-7xl items-center justify-between gap-4 px-4 sm:px-6">
        <div className="flex items-center gap-6">
          <Logo href={authed ? '/dashboard' : '/'} />
          <nav className="hidden items-center gap-1 text-sm md:flex">
            {authed && (
              <Button variant="ghost" size="sm" asChild>
                <Link href="/dashboard">Dashboard</Link>
              </Button>
            )}
            <Button variant="ghost" size="sm" asChild>
              <Link href="/join">Join a room</Link>
            </Button>
            {authed && hasRole(user, 'moderator', 'admin') && (
              <Button variant="ghost" size="sm" asChild>
                <Link href="/moderation" className="gap-1.5">
                  <ShieldCheck className="h-4 w-4" />
                  Moderation
                </Link>
              </Button>
            )}
          </nav>
        </div>

        <div className="flex items-center gap-2">
          <ThemeToggle />
          {!authed ? (
            <>
              <Button variant="ghost" size="sm" asChild>
                <Link href="/login">Sign in</Link>
              </Button>
              <Button size="sm" asChild>
                <Link href="/register">Get started</Link>
              </Button>
            </>
          ) : (
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <button
                  className="flex items-center gap-2 rounded-full focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  aria-label="Account menu"
                >
                  <Avatar>
                    <AvatarFallback>{initials(user.display_name)}</AvatarFallback>
                  </Avatar>
                </button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="w-56">
                <DropdownMenuLabel>
                  <div className="flex flex-col">
                    <span className="truncate text-sm font-medium">{user.display_name}</span>
                    <span className="truncate text-xs font-normal text-muted-foreground">
                      {user.email} · {user.role}
                    </span>
                  </div>
                </DropdownMenuLabel>
                <DropdownMenuSeparator />
                <DropdownMenuItem asChild>
                  <Link href="/dashboard">Dashboard</Link>
                </DropdownMenuItem>
                {hasRole(user, 'moderator', 'admin') && (
                  <DropdownMenuItem asChild>
                    <Link href="/moderation">Moderation queue</Link>
                  </DropdownMenuItem>
                )}
                <DropdownMenuSeparator />
                <DropdownMenuItem
                  onClick={async () => {
                    await logout();
                    router.push('/');
                  }}
                >
                  <LogOut className="h-4 w-4" />
                  Sign out
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          )}
        </div>
      </div>
    </header>
  );
}
