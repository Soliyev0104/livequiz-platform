'use client';

import { Check, CircleSlash, X } from 'lucide-react';
import * as React from 'react';

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Leaderboard } from '@/features/live-match/Leaderboard';
import type { MyAnswer } from '@/features/live-match/store';
import type { LeaderboardEntry, QuestionClosedPayload, QuestionStartedPayload } from '@/lib/types';
import { cn } from '@/lib/utils';

interface Props {
  question: QuestionStartedPayload;
  closed: QuestionClosedPayload;
  myAnswer: MyAnswer | null;
  leaderboard: LeaderboardEntry[];
  participantId: string;
}

export function BetweenLeaderboard({
  question,
  closed,
  myAnswer,
  leaderboard,
  participantId,
}: Props): React.JSX.Element {
  const correctIds = new Set(closed.correct_option_ids);
  const answered = !!myAnswer && myAnswer.matchQuestionId === closed.match_question_id;
  const mySelection = answered ? myAnswer.selectedOptionIds : [];
  const gotItRight =
    answered &&
    mySelection.length > 0 &&
    mySelection.every((id) => correctIds.has(id)) &&
    correctIds.size === mySelection.length;

  const myEntry = leaderboard.find((e) => e.participant_id === participantId) ?? null;

  return (
    <div className="mx-auto w-full max-w-3xl space-y-5">
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="flex items-center justify-between text-base">
            <span>Question {question.position} results</span>
            {answered ? (
              gotItRight ? (
                <span className="flex items-center gap-1.5 text-sm font-medium text-success">
                  <Check className="h-4 w-4" /> Correct
                </span>
              ) : (
                <span className="flex items-center gap-1.5 text-sm font-medium text-destructive">
                  <X className="h-4 w-4" /> Incorrect
                </span>
              )
            ) : (
              <span className="flex items-center gap-1.5 text-sm font-medium text-muted-foreground">
                <CircleSlash className="h-4 w-4" /> No answer
              </span>
            )}
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <p className="text-sm font-medium">{question.question.body}</p>
          <ul className="space-y-2">
            {question.question.options.map((opt) => {
              const isCorrect = correctIds.has(opt.id);
              const mine = mySelection.includes(opt.id);
              return (
                <li
                  key={opt.id}
                  className={cn(
                    'flex items-center gap-2 rounded-lg border px-3 py-2 text-sm',
                    isCorrect ? 'border-success bg-success/10' : 'border-border/60',
                    mine && !isCorrect && 'border-destructive/60 bg-destructive/5',
                  )}
                >
                  <span className="flex-1">{opt.body}</span>
                  {isCorrect && (
                    <span className="flex items-center gap-1 text-xs font-medium text-success">
                      <Check className="h-3.5 w-3.5" /> Correct answer
                    </span>
                  )}
                  {mine && (
                    <span className="text-xs font-medium text-muted-foreground">Your pick</span>
                  )}
                </li>
              );
            })}
          </ul>
          {(typeof closed.accuracy_percent === 'number' || closed.explanation) && (
            <div className="rounded-lg border border-border/60 bg-muted/30 p-3 text-sm">
              {typeof closed.accuracy_percent === 'number' && (
                <p className="text-muted-foreground">{closed.accuracy_percent.toFixed(1)}% answered correctly.</p>
              )}
              {closed.explanation && <p className="mt-1">{closed.explanation}</p>}
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="flex items-center justify-between text-base">
            Leaderboard
            {myEntry && <span className="text-sm font-normal text-muted-foreground">You: #{myEntry.rank}</span>}
          </CardTitle>
        </CardHeader>
        <CardContent>
          <Leaderboard
            entries={leaderboard}
            highlightParticipantId={participantId}
            emptyHint="Scores update after the first question."
          />
        </CardContent>
      </Card>
    </div>
  );
}
