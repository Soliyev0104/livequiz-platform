'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { BarChart3, LayoutDashboard, PlusCircle, ShieldCheck } from 'lucide-react';
import * as React from 'react';

import { hasRole, useAuthStore } from '@/lib/auth';
import { cn } from '@/lib/utils';

interface NavItem {
  href: string;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  match: (path: string) => boolean;
}

export function Sidebar(): React.JSX.Element {
  const pathname = usePathname();
  const user = useAuthStore((s) => s.user);

  const items: NavItem[] = [
    {
      href: '/dashboard',
      label: 'Dashboard',
      icon: LayoutDashboard,
      match: (p) => p === '/dashboard',
    },
    {
      href: '/quiz-sets/new',
      label: 'New quiz',
      icon: PlusCircle,
      match: (p) => p.startsWith('/quiz-sets'),
    },
  ];
  if (hasRole(user, 'moderator', 'admin')) {
    items.push({
      href: '/moderation',
      label: 'Moderation',
      icon: ShieldCheck,
      match: (p) => p.startsWith('/moderation'),
    });
  }

  return (
    <aside className="hidden w-56 shrink-0 border-r border-border/70 lg:block">
      <nav className="sticky top-16 flex flex-col gap-1 p-4">
        {items.map((item) => {
          const active = item.match(pathname);
          const Icon = item.icon;
          return (
            <Link
              key={item.href}
              href={item.href}
              className={cn(
                'flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors',
                active
                  ? 'bg-accent text-accent-foreground'
                  : 'text-muted-foreground hover:bg-accent/60 hover:text-foreground',
              )}
            >
              <Icon className="h-4 w-4" />
              {item.label}
            </Link>
          );
        })}
        <div className="mt-2 rounded-lg border border-dashed border-border/60 p-3 text-xs text-muted-foreground">
          <div className="mb-1 flex items-center gap-1.5 font-medium text-foreground">
            <BarChart3 className="h-3.5 w-3.5" /> Tip
          </div>
          Run a room from a published quiz to collect live analytics.
        </div>
      </nav>
    </aside>
  );
}
