'use client';

import { Check, Send } from 'lucide-react';
import * as React from 'react';

import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { AnswerFeedback } from '@/features/play/AnswerFeedback';
import { TimerBar } from '@/features/live-match/TimerBar';
import type { MyAnswer } from '@/features/live-match/store';
import { useCountdown } from '@/features/live-match/useCountdown';
import type { QuestionStartedPayload } from '@/lib/types';
import { cn } from '@/lib/utils';

const LABELS = ['A', 'B', 'C', 'D', 'E', 'F'];
const COLORS = [
  'bg-rose-500 hover:bg-rose-500/90',
  'bg-sky-500 hover:bg-sky-500/90',
  'bg-amber-500 hover:bg-amber-500/90',
  'bg-emerald-500 hover:bg-emerald-500/90',
  'bg-violet-500 hover:bg-violet-500/90',
  'bg-pink-500 hover:bg-pink-500/90',
];

interface Props {
  question: QuestionStartedPayload;
  myAnswer: MyAnswer | null;
  skewMs: number;
  questionCount?: number;
  onSubmit: (selectedOptionIds: string[]) => void;
}

export function PlayerQuestionScreen({
  question,
  myAnswer,
  skewMs,
  questionCount,
  onSubmit,
}: Props): React.JSX.Element {
  const isMulti = question.question.type === 'multiple_choice';
  const options = question.question.options;
  const cd = useCountdown(question.started_at, question.deadline_at, skewMs);
  const [selected, setSelected] = React.useState<string[]>([]);

  // Reset local selection when a new question arrives.
  React.useEffect(() => {
    setSelected([]);
  }, [question.match_question_id]);

  const answered = !!myAnswer && myAnswer.matchQuestionId === question.match_question_id;
  const locked = answered || cd.expired;

  const submitSingle = React.useCallback(
    (optionId: string) => {
      if (locked) return;
      setSelected([optionId]);
      onSubmit([optionId]);
    },
    [locked, onSubmit],
  );

  const toggleMulti = React.useCallback(
    (optionId: string) => {
      if (locked) return;
      setSelected((cur) => (cur.includes(optionId) ? cur.filter((x) => x !== optionId) : [...cur, optionId]));
    },
    [locked],
  );

  // Number keys 1..N select / submit.
  React.useEffect(() => {
    function onKey(e: KeyboardEvent): void {
      if (locked) return;
      const idx = Number(e.key) - 1;
      if (Number.isInteger(idx) && idx >= 0 && idx < options.length) {
        e.preventDefault();
        const id = options[idx].id;
        if (isMulti) toggleMulti(id);
        else submitSingle(id);
      }
    }
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [locked, options, isMulti, toggleMulti, submitSingle]);

  return (
    <div className="mx-auto w-full max-w-3xl space-y-5">
      <div className="flex items-center justify-between text-sm text-muted-foreground">
        <span>
          Question {question.position}
          {questionCount ? ` of ${questionCount}` : ''}
        </span>
        <span className="capitalize">{question.question.type.replace('_', ' ')}</span>
      </div>

      <TimerBar startedAt={question.started_at} deadlineAt={question.deadline_at} skewMs={skewMs} />

      <Card>
        <CardContent className="p-6">
          <h1 className="text-balance text-center text-2xl font-semibold leading-snug sm:text-3xl">
            {question.question.body}
          </h1>
        </CardContent>
      </Card>

      {answered ? (
        <AnswerFeedback answer={myAnswer} />
      ) : cd.expired ? (
        <div className="rounded-xl border border-destructive/40 bg-destructive/10 px-4 py-3 text-sm text-destructive">
          Time is up — waiting for the results.
        </div>
      ) : (
        <p className="text-center text-sm text-muted-foreground">
          {isMulti ? 'Select all that apply, then submit.' : 'Tap an answer (or press 1–4).'}
        </p>
      )}

      <div className={cn('grid gap-3', options.length > 2 ? 'sm:grid-cols-2' : 'grid-cols-1')}>
        {options.map((opt, i) => {
          const isSelected = selected.includes(opt.id);
          return (
            <button
              key={opt.id}
              type="button"
              disabled={locked && !isMulti}
              aria-pressed={isMulti ? isSelected : undefined}
              onClick={() => (isMulti ? toggleMulti(opt.id) : submitSingle(opt.id))}
              className={cn(
                'flex min-h-[4.5rem] items-center gap-4 rounded-xl px-5 py-4 text-left text-lg font-medium text-white shadow transition-transform focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-ring/60',
                COLORS[i % COLORS.length],
                !locked && 'active:scale-[0.98]',
                locked && !isSelected && 'opacity-40',
                isSelected && 'ring-4 ring-white/70',
              )}
            >
              <span className="grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-white/25 text-base font-bold">
                {isSelected ? <Check className="h-5 w-5" /> : LABELS[i] ?? i + 1}
              </span>
              <span className="flex-1">{opt.body}</span>
            </button>
          );
        })}
      </div>

      {isMulti && !answered && !cd.expired && (
        <Button
          size="lg"
          className="w-full"
          disabled={selected.length === 0}
          onClick={() => onSubmit(selected)}
        >
          <Send className="h-4 w-4" /> Submit answer
        </Button>
      )}
    </div>
  );
}
