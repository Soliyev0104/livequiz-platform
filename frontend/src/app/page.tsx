import Link from 'next/link';
import { BarChart3, Crown, Radio, ShieldCheck, Timer, Users } from 'lucide-react';
import * as React from 'react';

import { Footer } from '@/components/layout/Footer';
import { TopBar } from '@/components/layout/TopBar';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';

export default function HomePage(): React.JSX.Element {
  return (
    <div className="flex min-h-screen flex-col">
      <TopBar />

      <main className="flex-1">
        {/* Hero */}
        <section className="relative overflow-hidden border-b border-border/60">
          <div
            aria-hidden
            className="pointer-events-none absolute inset-0 bg-[radial-gradient(60%_50%_at_50%_0%,hsl(var(--primary)/0.18),transparent)]"
          />
          <div className="mx-auto grid max-w-7xl gap-10 px-4 py-16 sm:px-6 lg:grid-cols-2 lg:items-center lg:py-24">
            <div>
              <Badge variant="muted" className="mb-4">
                Real-time multiplayer quizzes
              </Badge>
              <h1 className="text-balance text-4xl font-bold tracking-tight sm:text-5xl">
                Host real-time quizzes with live leaderboards.
              </h1>
              <p className="mt-4 max-w-xl text-lg text-muted-foreground">
                Build a quiz, open a room, and watch players race through questions. Speed-bonus
                scoring, animated leaderboards, and a serious analytics panel after every match.
              </p>
              <div className="mt-8 flex flex-wrap gap-3">
                <Button size="lg" asChild>
                  <Link href="/join">Join a room</Link>
                </Button>
                <Button size="lg" variant="outline" asChild>
                  <Link href="/register">Create a quiz</Link>
                </Button>
                <Button size="lg" variant="ghost" asChild>
                  <Link href="/login">Sign in</Link>
                </Button>
              </div>
            </div>

            {/* Demo room preview */}
            <Card className="border-primary/20 bg-card/80 shadow-xl backdrop-blur">
              <CardHeader className="pb-3">
                <div className="flex items-center justify-between">
                  <CardTitle className="flex items-center gap-2 text-base">
                    <Radio className="h-4 w-4 text-primary" /> Live room preview
                  </CardTitle>
                  <span className="font-mono text-sm font-bold tracking-[0.25em] text-primary">DEMO01</span>
                </div>
                <CardDescription>Which transport protocol is connectionless?</CardDescription>
              </CardHeader>
              <CardContent className="space-y-3">
                <div className="grid grid-cols-2 gap-2 text-sm">
                  {[
                    { label: 'TCP', tone: 'bg-rose-500/15 text-rose-400' },
                    { label: 'UDP', tone: 'bg-emerald-500/15 text-emerald-400 ring-1 ring-emerald-500/40' },
                    { label: 'HTTP', tone: 'bg-amber-500/15 text-amber-400' },
                    { label: 'TLS', tone: 'bg-sky-500/15 text-sky-400' },
                  ].map((o) => (
                    <div key={o.label} className={`rounded-lg px-3 py-2 font-medium ${o.tone}`}>
                      {o.label}
                    </div>
                  ))}
                </div>
                <div className="flex items-center gap-2 text-xs text-muted-foreground">
                  <Timer className="h-3.5 w-3.5" /> 12s left
                  <span>·</span>
                  <Users className="h-3.5 w-3.5" /> 18 players
                </div>
                <div className="space-y-1.5 rounded-lg border border-border/60 bg-muted/30 p-3">
                  {[
                    { rank: 1, name: 'Marvel', score: 2410 },
                    { rank: 2, name: 'Avenger', score: 2280 },
                    { rank: 3, name: 'Azamat', score: 2105 },
                  ].map((e) => (
                    <div key={e.rank} className="flex items-center gap-2 text-sm">
                      <span className="grid h-6 w-6 place-items-center rounded-full bg-amber-400/15 text-xs font-bold text-amber-400">
                        {e.rank === 1 ? <Crown className="h-3 w-3" /> : e.rank}
                      </span>
                      <span className="flex-1">{e.name}</span>
                      <span className="font-mono tabular-nums">{e.score.toLocaleString()}</span>
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          </div>
        </section>

        {/* Feature cards */}
        <section className="mx-auto max-w-7xl px-4 py-16 sm:px-6">
          <div className="grid gap-6 md:grid-cols-3">
            <Card>
              <CardHeader>
                <div className="mb-2 grid h-10 w-10 place-items-center rounded-lg bg-primary/15 text-primary">
                  <Radio className="h-5 w-5" />
                </div>
                <CardTitle className="text-lg">Real-time rooms</CardTitle>
                <CardDescription>
                  WebSocket-powered rooms with snapshot-then-patches state, server-synced timers, and
                  automatic reconnect.
                </CardDescription>
              </CardHeader>
            </Card>
            <Card>
              <CardHeader>
                <div className="mb-2 grid h-10 w-10 place-items-center rounded-lg bg-primary/15 text-primary">
                  <BarChart3 className="h-5 w-5" />
                </div>
                <CardTitle className="text-lg">Match analytics</CardTitle>
                <CardDescription>
                  Per-question accuracy, response-time distribution, most-missed questions, and the
                  final leaderboard.
                </CardDescription>
              </CardHeader>
            </Card>
            <Card>
              <CardHeader>
                <div className="mb-2 grid h-10 w-10 place-items-center rounded-lg bg-primary/15 text-primary">
                  <ShieldCheck className="h-5 w-5" />
                </div>
                <CardTitle className="text-lg">Moderation</CardTitle>
                <CardDescription>
                  A review queue for reported players, quizzes, and rooms — dismiss, hide, mute, or
                  ban with an audit trail.
                </CardDescription>
              </CardHeader>
            </Card>
          </div>
        </section>
      </main>

      <Footer />
    </div>
  );
}
