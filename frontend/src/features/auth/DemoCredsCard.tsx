'use client';

import * as React from 'react';

import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { DEMO_CREDENTIALS, DEMO_MODE } from '@/lib/env';

export function DemoCredsCard({
  onPick,
}: {
  onPick?: (email: string, password: string) => void;
}): React.JSX.Element | null {
  if (!DEMO_MODE) return null;
  return (
    <Card className="border-dashed bg-accent/30">
      <CardHeader className="pb-3">
        <CardTitle className="text-base">Demo credentials</CardTitle>
        <CardDescription>Seeded accounts for trying the platform.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-2">
        {DEMO_CREDENTIALS.map((c) => (
          <div
            key={c.email}
            className="flex items-center justify-between gap-2 rounded-md border border-border/60 bg-background/60 px-3 py-2 text-sm"
          >
            <div className="min-w-0">
              <div className="font-medium">{c.label}</div>
              <div className="truncate text-muted-foreground">
                {c.email} / {c.password}
              </div>
            </div>
            {onPick && (
              <Button type="button" size="sm" variant="outline" onClick={() => onPick(c.email, c.password)}>
                Use
              </Button>
            )}
          </div>
        ))}
      </CardContent>
    </Card>
  );
}
