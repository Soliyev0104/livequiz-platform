'use client';

import Link from 'next/link';
import { ArrowLeft, Camera, TrendingDown } from 'lucide-react';
import * as React from 'react';
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ResponsiveContainer,
  Tooltip as RTooltip,
  XAxis,
  YAxis,
} from 'recharts';

import { AppShell } from '@/components/AppShell';
import { AuthGuard } from '@/components/AuthGuard';
import { EmptyState } from '@/components/EmptyState';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { useMatchAnalytics } from '@/features/analytics/hooks';
import { ApiError } from '@/lib/api-client';
import { formatMs, formatPercent } from '@/lib/utils';
import type { AnalyticsResponse } from '@/lib/types';

const AXIS = 'hsl(var(--muted-foreground))';
const GRID = 'hsl(var(--border))';

function ChartTooltip({
  active,
  payload,
  label,
}: {
  active?: boolean;
  payload?: Array<{ value: number; name: string }>;
  label?: string | number;
}): React.JSX.Element | null {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-md border bg-popover px-3 py-2 text-xs text-popover-foreground shadow">
      {label !== undefined && <div className="mb-1 font-medium">{label}</div>}
      {payload.map((p) => (
        <div key={p.name}>
          {p.name}: {p.value}
        </div>
      ))}
    </div>
  );
}

function AccuracyChart({ data }: { data: AnalyticsResponse['question_accuracy'] }): React.JSX.Element {
  const rows = (data ?? []).map((r, i) => ({
    name: `Q${i + 1}`,
    accuracy: Math.round(r.accuracy_percent),
    questionId: r.question_id,
  }));
  if (rows.length === 0) return <p className="text-sm text-muted-foreground">No question data.</p>;
  return (
    <ResponsiveContainer width="100%" height={260}>
      <BarChart data={rows} margin={{ top: 8, right: 8, bottom: 0, left: -16 }}>
        <CartesianGrid stroke={GRID} strokeDasharray="3 3" vertical={false} />
        <XAxis dataKey="name" stroke={AXIS} fontSize={12} tickLine={false} axisLine={false} />
        <YAxis stroke={AXIS} fontSize={12} tickLine={false} axisLine={false} domain={[0, 100]} unit="%" />
        <RTooltip content={<ChartTooltip />} cursor={{ fill: 'hsl(var(--muted))', opacity: 0.4 }} />
        <Bar dataKey="accuracy" name="Accuracy %" radius={[4, 4, 0, 0]}>
          {rows.map((r) => (
            <Cell
              key={r.questionId}
              fill={r.accuracy >= 70 ? 'hsl(var(--success))' : r.accuracy >= 40 ? 'hsl(var(--primary))' : 'hsl(var(--destructive))'}
            />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}

function ResponseTimeChart({
  dist,
}: {
  dist: AnalyticsResponse['response_time_distribution'];
}): React.JSX.Element {
  if (!dist) return <p className="text-sm text-muted-foreground">No response-time data.</p>;
  const rows = [
    { name: 'p50', ms: Math.round(dist.p50_ms) },
    { name: 'avg', ms: Math.round(dist.avg_ms) },
    { name: 'p95', ms: Math.round(dist.p95_ms) },
    { name: 'p99', ms: Math.round(dist.p99_ms) },
  ];
  return (
    <ResponsiveContainer width="100%" height={260}>
      <BarChart data={rows} margin={{ top: 8, right: 8, bottom: 0, left: -8 }}>
        <CartesianGrid stroke={GRID} strokeDasharray="3 3" vertical={false} />
        <XAxis dataKey="name" stroke={AXIS} fontSize={12} tickLine={false} axisLine={false} />
        <YAxis stroke={AXIS} fontSize={12} tickLine={false} axisLine={false} unit=" ms" />
        <RTooltip content={<ChartTooltip />} cursor={{ fill: 'hsl(var(--muted))', opacity: 0.4 }} />
        <Bar dataKey="ms" name="Response time (ms)" fill="hsl(var(--primary))" radius={[4, 4, 0, 0]} />
      </BarChart>
    </ResponsiveContainer>
  );
}

function AnalyticsInner({ matchId }: { matchId: string }): React.JSX.Element {
  const { data, isLoading, isError, error } = useMatchAnalytics(matchId);

  if (isLoading) {
    return (
      <div className="mx-auto w-full max-w-6xl px-4 py-8 sm:px-6">
        <Skeleton className="mb-6 h-9 w-72" />
        <div className="grid gap-4 lg:grid-cols-2">
          <Skeleton className="h-72 w-full rounded-xl" />
          <Skeleton className="h-72 w-full rounded-xl" />
          <Skeleton className="h-72 w-full rounded-xl" />
          <Skeleton className="h-72 w-full rounded-xl" />
        </div>
      </div>
    );
  }

  if (isError || !data) {
    const msg =
      error instanceof ApiError
        ? error.status === 404
          ? 'Analytics are not available for this match yet — they are generated when the match finishes.'
          : error.message
        : 'Could not load analytics.';
    return (
      <div className="mx-auto w-full max-w-2xl px-4 py-16">
        <EmptyState
          title="Analytics unavailable"
          description={msg}
          action={
            <Button asChild variant="outline">
              <Link href="/dashboard">Back to dashboard</Link>
            </Button>
          }
        />
      </div>
    );
  }

  const board = data.final_leaderboard ?? [];
  const mostMissed = data.most_missed_questions ?? [];

  return (
    <div className="mx-auto w-full max-w-6xl px-4 py-8 sm:px-6">
      <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <Button variant="ghost" size="icon" asChild>
            <Link href="/dashboard" aria-label="Back to dashboard">
              <ArrowLeft className="h-4 w-4" />
            </Link>
          </Button>
          <div>
            <h1 className="text-2xl font-semibold leading-tight">Match analytics</h1>
            <p className="text-sm text-muted-foreground">
              {data.total_answers.toLocaleString()} answers · match {matchId}
            </p>
          </div>
        </div>
        <Button variant="outline" size="sm" onClick={() => window.print()}>
          <Camera className="h-4 w-4" /> Export (print / screenshot)
        </Button>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-base">Question accuracy</CardTitle>
            <CardDescription>Percent of answers correct, per question.</CardDescription>
          </CardHeader>
          <CardContent>
            <AccuracyChart data={data.question_accuracy} />
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-base">Response time distribution</CardTitle>
            <CardDescription>How quickly players answered (milliseconds).</CardDescription>
          </CardHeader>
          <CardContent>
            <ResponseTimeChart dist={data.response_time_distribution} />
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="flex items-center gap-2 text-base">
              <TrendingDown className="h-4 w-4 text-destructive" /> Most missed questions
            </CardTitle>
          </CardHeader>
          <CardContent>
            {mostMissed.length === 0 ? (
              <p className="text-sm text-muted-foreground">No data available.</p>
            ) : (
              <ul className="space-y-2">
                {mostMissed.map((q, i) => (
                  <li
                    key={q.question_id}
                    className="flex items-center justify-between gap-3 rounded-lg border border-border/60 px-3 py-2 text-sm"
                  >
                    <span className="min-w-0 flex-1 truncate">Question {i + 1} · #{q.question_id}</span>
                    <span className="shrink-0 font-medium text-destructive">{formatPercent(q.accuracy_percent)}</span>
                    <span className="shrink-0 text-muted-foreground">{formatMs(q.avg_response_ms)}</span>
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-base">Final leaderboard</CardTitle>
          </CardHeader>
          <CardContent>
            {board.length === 0 ? (
              <p className="text-sm text-muted-foreground">No participants.</p>
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="w-12">#</TableHead>
                    <TableHead>Player</TableHead>
                    <TableHead className="text-right">Score</TableHead>
                    <TableHead className="text-right">Correct</TableHead>
                    <TableHead className="text-right">Avg time</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {board.map((r) => (
                    <TableRow key={r.participant_id}>
                      <TableCell className="font-medium">{r.rank}</TableCell>
                      <TableCell className="max-w-[12rem] truncate">{r.nickname || 'Player'}</TableCell>
                      <TableCell className="text-right font-mono tabular-nums">
                        {r.total_score.toLocaleString()}
                      </TableCell>
                      <TableCell className="text-right tabular-nums">{r.correct_count}</TableCell>
                      <TableCell className="text-right tabular-nums text-muted-foreground">
                        {formatMs(r.average_response_ms)}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

export function AnalyticsView({ matchId }: { matchId: string }): React.JSX.Element {
  return (
    <AuthGuard requireRole={['host', 'admin']}>
      <AppShell>
        <AnalyticsInner matchId={matchId} />
      </AppShell>
    </AuthGuard>
  );
}
