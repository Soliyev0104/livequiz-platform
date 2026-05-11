'use client';

import { AlertTriangle, CheckCircle2, Loader2, Rocket } from 'lucide-react';
import * as React from 'react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import type { QuizSetDetail } from '@/lib/types';

interface ValidationPanelProps {
  quiz: QuizSetDetail;
  ok: boolean;
  globalIssues: string[];
  perQuestion: Record<string, string[]>;
  selectedQuestionId: string | null;
  selectedIndex: number | null;
  publishing: boolean;
  publishError: string | null;
  onPublish: () => void;
}

export function ValidationPanel({
  quiz,
  ok,
  globalIssues,
  perQuestion,
  selectedQuestionId,
  selectedIndex,
  publishing,
  publishError,
  onPublish,
}: ValidationPanelProps): React.JSX.Element {
  const selectedIssues = selectedQuestionId ? perQuestion[selectedQuestionId] ?? [] : [];
  const invalidQuestionCount = Object.values(perQuestion).filter((a) => a.length > 0).length;

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="flex items-center justify-between text-base">
            Publish checklist
            {ok ? (
              <Badge variant="success">Ready</Badge>
            ) : (
              <Badge variant="muted">{invalidQuestionCount + globalIssues.length} to fix</Badge>
            )}
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3 text-sm">
          <ChecklistItem ok={quiz.question_count > 0} label="At least one question" />
          <ChecklistItem ok={invalidQuestionCount === 0} label="All questions valid" />
          <ChecklistItem ok={!!quiz.title.trim()} label="Quiz has a title" />

          {globalIssues.length > 0 && (
            <ul className="space-y-1 rounded-md border border-amber-500/40 bg-amber-500/10 p-2 text-amber-600 dark:text-amber-400">
              {globalIssues.map((m) => (
                <li key={m}>· {m}</li>
              ))}
            </ul>
          )}

          {selectedIssues.length > 0 && (
            <div className="rounded-md border border-amber-500/40 bg-amber-500/10 p-2 text-amber-600 dark:text-amber-400">
              <p className="mb-1 font-medium">
                Question {selectedIndex !== null ? selectedIndex + 1 : ''}
              </p>
              <ul className="space-y-1">
                {selectedIssues.map((m) => (
                  <li key={m}>· {m}</li>
                ))}
              </ul>
            </div>
          )}

          {publishError && (
            <div className="flex items-start gap-2 rounded-md border border-destructive/40 bg-destructive/10 p-2 text-destructive">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
              <span>{publishError}</span>
            </div>
          )}

          <Button className="w-full" onClick={onPublish} disabled={publishing}>
            {publishing ? <Loader2 className="h-4 w-4 animate-spin" /> : <Rocket className="h-4 w-4" />}
            {quiz.is_published ? 'Re-publish' : 'Publish quiz'}
          </Button>
          {quiz.is_published && (
            <p className="text-xs text-muted-foreground">
              This quiz is published — hosts can run rooms from it.
            </p>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function ChecklistItem({ ok, label }: { ok: boolean; label: string }): React.JSX.Element {
  return (
    <div className="flex items-center gap-2">
      {ok ? (
        <CheckCircle2 className="h-4 w-4 text-success" />
      ) : (
        <AlertTriangle className="h-4 w-4 text-amber-500" />
      )}
      <span className={ok ? '' : 'text-muted-foreground'}>{label}</span>
    </div>
  );
}
