'use client';

import Link from 'next/link';
import { BarChart3, FileQuestion, PlusCircle, Radio, Trophy } from 'lucide-react';
import * as React from 'react';

import { AppShell } from '@/components/AppShell';
import { AuthGuard } from '@/components/AuthGuard';
import { EmptyState } from '@/components/EmptyState';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { useMyQuizSets } from '@/features/dashboard/hooks';
import { QuizSetCard } from '@/features/dashboard/QuizSetCard';
import { useRecentRooms } from '@/features/dashboard/recent-rooms';
import { useAuthStore } from '@/lib/auth';
import { formatRelativeTime } from '@/lib/utils';

function StatCard({
  icon,
  label,
  value,
}: {
  icon: React.ReactNode;
  label: string;
  value: React.ReactNode;
}): React.JSX.Element {
  return (
    <Card>
      <CardContent className="flex items-center gap-4 p-5">
        <div className="grid h-11 w-11 place-items-center rounded-lg bg-primary/15 text-primary">{icon}</div>
        <div>
          <div className="text-2xl font-semibold">{value}</div>
          <div className="text-sm text-muted-foreground">{label}</div>
        </div>
      </CardContent>
    </Card>
  );
}

function DashboardInner(): React.JSX.Element {
  const user = useAuthStore((s) => s.user);
  const isHost = user?.role === 'host' || user?.role === 'admin';
  const { data, isLoading, isError } = useMyQuizSets(user?.id);
  const recentRooms = useRecentRooms();

  const quizzes = data?.items ?? [];
  const totalQuestions = quizzes.reduce((acc, q) => acc + q.question_count, 0);
  const publishedCount = quizzes.filter((q) => q.is_published).length;

  return (
    <div className="mx-auto w-full max-w-7xl px-4 py-8 sm:px-6">
      <div className="mb-8 flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-3xl font-semibold tracking-tight">
            {user ? `Welcome, ${user.display_name}` : 'Dashboard'}
          </h1>
          <p className="mt-1 text-muted-foreground">
            {isHost ? 'Build quizzes and run live rooms.' : 'Join a room or explore quizzes.'}
          </p>
        </div>
        {isHost && (
          <Button asChild>
            <Link href="/quiz-sets/new" className="gap-1.5">
              <PlusCircle className="h-4 w-4" /> Create quiz
            </Link>
          </Button>
        )}
      </div>

      <div className="mb-8 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard icon={<FileQuestion className="h-5 w-5" />} label="Quiz sets" value={isLoading ? '—' : quizzes.length} />
        <StatCard icon={<Trophy className="h-5 w-5" />} label="Published" value={isLoading ? '—' : publishedCount} />
        <StatCard icon={<BarChart3 className="h-5 w-5" />} label="Total questions" value={isLoading ? '—' : totalQuestions} />
        <StatCard icon={<Radio className="h-5 w-5" />} label="Recent rooms" value={recentRooms.length} />
      </div>

      <div className="grid gap-8 lg:grid-cols-[1fr_320px]">
        <section>
          <div className="mb-4 flex items-center justify-between">
            <h2 className="text-xl font-semibold">My quiz sets</h2>
          </div>

          {isLoading ? (
            <div className="grid gap-4 sm:grid-cols-2">
              {Array.from({ length: 4 }).map((_, i) => (
                <Skeleton key={i} className="h-44 w-full rounded-xl" />
              ))}
            </div>
          ) : isError ? (
            <EmptyState
              title="Could not load your quizzes"
              description="Please refresh the page."
            />
          ) : quizzes.length === 0 ? (
            <EmptyState
              icon={<FileQuestion className="h-10 w-10" />}
              title="No quiz sets yet"
              description={
                isHost
                  ? 'Create your first quiz to start hosting live rooms.'
                  : 'Your account does not own any quiz sets.'
              }
              action={
                isHost ? (
                  <Button asChild>
                    <Link href="/quiz-sets/new" className="gap-1.5">
                      <PlusCircle className="h-4 w-4" /> Create quiz
                    </Link>
                  </Button>
                ) : undefined
              }
            />
          ) : (
            <div className="grid gap-4 sm:grid-cols-2">
              {quizzes.map((q) => (
                <QuizSetCard key={q.id} quiz={q} />
              ))}
            </div>
          )}
        </section>

        <aside className="space-y-6">
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-base">Recent rooms</CardTitle>
              <CardDescription>Rooms you have hosted from this browser.</CardDescription>
            </CardHeader>
            <CardContent>
              {recentRooms.length === 0 ? (
                <p className="text-sm text-muted-foreground">
                  Host a published quiz and it will appear here.
                </p>
              ) : (
                <ul className="space-y-2">
                  {recentRooms.map((r) => (
                    <li key={r.code}>
                      <Link
                        href={`/host/rooms/${r.code}`}
                        className="flex items-center justify-between gap-2 rounded-md border border-border/60 px-3 py-2 text-sm transition-colors hover:bg-accent/60"
                      >
                        <div className="min-w-0">
                          <div className="font-mono font-semibold tracking-wider">{r.code}</div>
                          <div className="truncate text-muted-foreground">{r.quizTitle}</div>
                        </div>
                        <span className="shrink-0 text-xs text-muted-foreground">
                          {formatRelativeTime(r.createdAt)}
                        </span>
                      </Link>
                    </li>
                  ))}
                </ul>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-base">Quick actions</CardTitle>
            </CardHeader>
            <CardContent className="space-y-2">
              <Button variant="outline" className="w-full justify-start" asChild>
                <Link href="/join">Join a room as a player</Link>
              </Button>
              {isHost && (
                <Button variant="outline" className="w-full justify-start" asChild>
                  <Link href="/quiz-sets/new">Create a new quiz</Link>
                </Button>
              )}
            </CardContent>
          </Card>

          {publishedCount === 0 && quizzes.length > 0 && (
            <div className="rounded-lg border border-dashed border-border/70 p-4 text-sm text-muted-foreground">
              <Badge variant="muted" className="mb-2">
                Heads up
              </Badge>
              <p>None of your quizzes are published yet. Open one and click Publish to host a room.</p>
            </div>
          )}
        </aside>
      </div>
    </div>
  );
}

export function DashboardView(): React.JSX.Element {
  return (
    <AuthGuard>
      <AppShell withSidebar>
        <DashboardInner />
      </AppShell>
    </AuthGuard>
  );
}
