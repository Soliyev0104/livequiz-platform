'use client';

import { Check, Loader2, Plus, Save, Trash2, X } from 'lucide-react';
import * as React from 'react';
import { toast } from 'sonner';

import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input, Textarea } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { useDeleteQuestion, useUpdateQuestion } from '@/features/quiz-builder/hooks';
import { correctCount, toDraft, validateQuestion, type DraftOption, type DraftQuestion } from '@/features/quiz-builder/validation';
import { ApiError } from '@/lib/api-client';
import type { QuestionDetail, QuestionType } from '@/lib/types';
import { cn } from '@/lib/utils';

function defaultOptionsForType(type: QuestionType, current: DraftOption[]): DraftOption[] {
  if (type === 'true_false') {
    const trueCorrect = current.find((o) => /true/i.test(o.body))?.is_correct ?? true;
    return [
      { body: 'True', is_correct: trueCorrect },
      { body: 'False', is_correct: !trueCorrect },
    ];
  }
  let opts = current.length ? current : [
    { body: '', is_correct: true },
    { body: '', is_correct: false },
  ];
  if (type !== 'multiple_choice' && correctCount({ options: opts }) !== 1) {
    let kept = false;
    opts = opts.map((o) => {
      if (o.is_correct && !kept) {
        kept = true;
        return o;
      }
      return { ...o, is_correct: false };
    });
    if (!kept && opts[0]) opts = opts.map((o, i) => ({ ...o, is_correct: i === 0 }));
  }
  return opts;
}

interface QuestionEditorProps {
  quizId: string;
  question: QuestionDetail;
  index: number;
  onDeleted: () => void;
}

export function QuestionEditor({
  quizId,
  question,
  index,
  onDeleted,
}: QuestionEditorProps): React.JSX.Element {
  const update = useUpdateQuestion(quizId);
  const del = useDeleteQuestion(quizId);
  const [draft, setDraft] = React.useState<DraftQuestion>(() => toDraft(question));
  const [dirty, setDirty] = React.useState(false);

  // When a different question is selected (or it was re-fetched and we are
  // not mid-edit), re-sync the local draft.
  React.useEffect(() => {
    setDraft(toDraft(question));
    setDirty(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [question.id]);

  function patch(partial: Partial<DraftQuestion>): void {
    setDraft((d) => ({ ...d, ...partial }));
    setDirty(true);
  }

  function setOption(i: number, partial: Partial<DraftOption>): void {
    setDraft((d) => ({
      ...d,
      options: d.options.map((o, idx) => (idx === i ? { ...o, ...partial } : o)),
    }));
    setDirty(true);
  }

  function setCorrect(i: number, value: boolean): void {
    setDraft((d) => {
      if (d.type === 'multiple_choice') {
        return { ...d, options: d.options.map((o, idx) => (idx === i ? { ...o, is_correct: value } : o)) };
      }
      return { ...d, options: d.options.map((o, idx) => ({ ...o, is_correct: idx === i })) };
    });
    setDirty(true);
  }

  function addOption(): void {
    if (draft.options.length >= 6) return;
    setDraft((d) => ({ ...d, options: [...d.options, { body: '', is_correct: false }] }));
    setDirty(true);
  }

  function removeOption(i: number): void {
    if (draft.options.length <= 2) return;
    setDraft((d) => {
      const next = d.options.filter((_, idx) => idx !== i);
      if (d.type !== 'multiple_choice' && correctCount({ options: next }) === 0 && next[0]) {
        next[0] = { ...next[0], is_correct: true };
      }
      return { ...d, options: next };
    });
    setDirty(true);
  }

  function changeType(type: QuestionType): void {
    setDraft((d) => ({ ...d, type, options: defaultOptionsForType(type, d.options) }));
    setDirty(true);
  }

  const issues = validateQuestion(draft);
  const isMulti = draft.type === 'multiple_choice';

  async function save(): Promise<void> {
    if (issues.length > 0) {
      toast.error('Fix the highlighted issues before saving.');
      return;
    }
    try {
      await update.mutateAsync({
        questionId: draft.id,
        body: {
          body: draft.body.trim(),
          type: draft.type,
          time_limit_seconds: draft.time_limit_seconds,
          points: draft.points,
          explanation: draft.explanation.trim() ? draft.explanation.trim() : null,
          options: draft.options.map((o, i) => ({
            position: i + 1,
            body: o.body.trim(),
            is_correct: o.is_correct,
          })),
        },
      });
      setDirty(false);
      toast.success('Question saved');
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : 'Could not save the question');
    }
  }

  async function remove(): Promise<void> {
    if (!window.confirm('Delete this question?')) return;
    try {
      await del.mutateAsync(draft.id);
      onDeleted();
      toast.success('Question deleted');
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : 'Could not delete the question');
    }
  }

  return (
    <Card className="flex h-full flex-col">
      <CardHeader className="flex flex-row items-center justify-between gap-2 space-y-0 pb-3">
        <CardTitle className="text-base">
          Question {index + 1}
          {dirty && <span className="ml-2 text-xs font-normal text-amber-500">Unsaved changes</span>}
        </CardTitle>
        <div className="flex items-center gap-2">
          <Button variant="ghost" size="sm" onClick={remove} disabled={del.isPending}>
            <Trash2 className="h-4 w-4" /> Delete
          </Button>
          <Button size="sm" onClick={save} disabled={update.isPending || !dirty}>
            {update.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
            Save
          </Button>
        </div>
      </CardHeader>
      <CardContent className="min-h-0 flex-1 space-y-5 overflow-y-auto">
        <div className="space-y-1.5">
          <Label htmlFor="q-body">Question</Label>
          <Textarea
            id="q-body"
            rows={2}
            value={draft.body}
            onChange={(e) => patch({ body: e.target.value })}
            placeholder="Which transport protocol is connectionless?"
          />
        </div>

        <div className="grid gap-4 sm:grid-cols-3">
          <div className="space-y-1.5">
            <Label htmlFor="q-type">Type</Label>
            <Select value={draft.type} onValueChange={(v) => changeType(v as QuestionType)}>
              <SelectTrigger id="q-type">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="single_choice">Single choice</SelectItem>
                <SelectItem value="multiple_choice">Multiple choice</SelectItem>
                <SelectItem value="true_false">True / False</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="q-time">Time limit (s)</Label>
            <Input
              id="q-time"
              type="number"
              min={5}
              max={120}
              value={draft.time_limit_seconds}
              onChange={(e) => patch({ time_limit_seconds: Number(e.target.value) || 0 })}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="q-points">Points</Label>
            <Input
              id="q-points"
              type="number"
              min={0}
              max={10000}
              step={50}
              value={draft.points}
              onChange={(e) => patch({ points: Number(e.target.value) || 0 })}
            />
          </div>
        </div>

        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <Label>Answer options</Label>
            <span className="text-xs text-muted-foreground">
              {isMulti ? 'Check all correct answers' : 'Select the one correct answer'}
            </span>
          </div>
          <div className="space-y-2">
            {draft.options.map((opt, i) => (
              <div
                key={i}
                className={cn(
                  'flex items-center gap-2 rounded-md border px-2 py-1.5',
                  opt.is_correct ? 'border-success/50 bg-success/5' : 'border-border/60',
                )}
              >
                <button
                  type="button"
                  onClick={() => setCorrect(i, isMulti ? !opt.is_correct : true)}
                  aria-pressed={opt.is_correct}
                  aria-label={opt.is_correct ? 'Marked correct' : 'Mark correct'}
                  className={cn(
                    'grid h-6 w-6 shrink-0 place-items-center rounded-full border transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
                    isMulti ? 'rounded-md' : 'rounded-full',
                    opt.is_correct
                      ? 'border-success bg-success text-success-foreground'
                      : 'border-border bg-background',
                  )}
                >
                  {opt.is_correct && <Check className="h-3.5 w-3.5" />}
                </button>
                <Input
                  value={opt.body}
                  onChange={(e) => setOption(i, { body: e.target.value })}
                  placeholder={`Option ${i + 1}`}
                  disabled={draft.type === 'true_false'}
                  className="h-8 border-0 bg-transparent shadow-none focus-visible:ring-0"
                />
                {draft.type !== 'true_false' && draft.options.length > 2 && (
                  <button
                    type="button"
                    onClick={() => removeOption(i)}
                    className="rounded p-1 text-muted-foreground hover:text-destructive focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                    aria-label={`Remove option ${i + 1}`}
                  >
                    <X className="h-4 w-4" />
                  </button>
                )}
              </div>
            ))}
          </div>
          {draft.type !== 'true_false' && draft.options.length < 6 && (
            <Button type="button" variant="ghost" size="sm" onClick={addOption}>
              <Plus className="h-4 w-4" /> Add option
            </Button>
          )}
        </div>

        <div className="space-y-1.5">
          <Label htmlFor="q-expl">Explanation (shown after the question closes)</Label>
          <Textarea
            id="q-expl"
            rows={2}
            value={draft.explanation}
            onChange={(e) => patch({ explanation: e.target.value })}
            placeholder="UDP is connectionless and does not establish a session before sending datagrams."
          />
        </div>

        {issues.length > 0 && (
          <ul className="space-y-1 rounded-md border border-amber-500/40 bg-amber-500/10 p-3 text-sm text-amber-600 dark:text-amber-400">
            {issues.map((msg) => (
              <li key={msg}>· {msg}</li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
