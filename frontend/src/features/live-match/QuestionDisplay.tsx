'use client';

import { Check } from 'lucide-react';
import * as React from 'react';

import { Card, CardContent } from '@/components/ui/card';
import { cn } from '@/lib/utils';
import type { QuestionClosedPayload, QuestionStartedPayload } from '@/lib/types';

const OPTION_LABELS = ['A', 'B', 'C', 'D', 'E', 'F'];

interface QuestionDisplayProps {
  question: QuestionStartedPayload;
  closed?: QuestionClosedPayload | null;
}

/** Read-only rendering of the live question (used by the host). Correct
 * answers are only revealed once `closed` is provided (after the deadline). */
export function QuestionDisplay({ question, closed }: QuestionDisplayProps): React.JSX.Element {
  const correctIds = new Set(closed?.correct_option_ids ?? []);
  const total = question.question.options.length;
  return (
    <Card>
      <CardContent className="space-y-4 p-6">
        <div className="flex items-center justify-between text-sm text-muted-foreground">
          <span>Question {question.position}</span>
          <span className="capitalize">{question.question.type.replace('_', ' ')}</span>
        </div>
        <h2 className="text-balance text-2xl font-semibold leading-snug">{question.question.body}</h2>
        <div className={cn('grid gap-3', total > 2 ? 'sm:grid-cols-2' : 'grid-cols-1')}>
          {question.question.options.map((opt, i) => {
            const isCorrect = closed && correctIds.has(opt.id);
            const isWrong = closed && !correctIds.has(opt.id);
            return (
              <div
                key={opt.id}
                className={cn(
                  'flex items-center gap-3 rounded-lg border px-4 py-3 text-base',
                  isCorrect && 'border-success bg-success/10',
                  isWrong && 'border-border/50 opacity-60',
                  !closed && 'border-border bg-card',
                )}
              >
                <span className="grid h-7 w-7 shrink-0 place-items-center rounded-md bg-muted text-sm font-bold">
                  {OPTION_LABELS[i] ?? i + 1}
                </span>
                <span className="flex-1">{opt.body}</span>
                {isCorrect && (
                  <span className="flex shrink-0 items-center gap-1 text-sm font-medium text-success">
                    <Check className="h-4 w-4" /> Correct
                  </span>
                )}
              </div>
            );
          })}
        </div>
        {closed && (
          <div className="space-y-1 rounded-lg border border-border/60 bg-muted/30 p-3 text-sm">
            {typeof closed.accuracy_percent === 'number' && (
              <p className="text-muted-foreground">
                {closed.accuracy_percent.toFixed(1)}% answered correctly.
              </p>
            )}
            {closed.explanation && <p>{closed.explanation}</p>}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
