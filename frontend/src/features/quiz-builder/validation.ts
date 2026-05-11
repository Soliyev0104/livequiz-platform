import type { QuestionDetail, QuestionType } from '@/lib/types';

export interface DraftOption {
  id?: string;
  body: string;
  is_correct: boolean;
}

export interface DraftQuestion {
  id: string;
  position: number;
  body: string;
  type: QuestionType;
  time_limit_seconds: number;
  points: number;
  explanation: string;
  options: DraftOption[];
}

export function toDraft(q: QuestionDetail): DraftQuestion {
  return {
    id: q.id,
    position: q.position,
    body: q.body,
    type: q.type,
    time_limit_seconds: q.time_limit_seconds,
    points: q.points,
    explanation: q.explanation ?? '',
    options: q.options
      .slice()
      .sort((a, b) => a.position - b.position)
      .map((o) => ({ id: o.id, body: o.body, is_correct: o.is_correct })),
  };
}

export function correctCount(q: { options: DraftOption[] }): number {
  return q.options.filter((o) => o.is_correct).length;
}

export function validateQuestion(q: DraftQuestion): string[] {
  const issues: string[] = [];
  if (!q.body.trim()) issues.push('Question text is required.');
  const filled = q.options.filter((o) => o.body.trim());
  if (filled.length < 2) issues.push('At least 2 answer options are required.');
  if (q.options.some((o) => !o.body.trim())) issues.push('Every option needs text.');
  const correct = correctCount(q);
  if (q.type === 'multiple_choice') {
    if (correct < 1) issues.push('Mark at least one correct answer.');
  } else if (correct !== 1) {
    issues.push('Mark exactly one correct answer.');
  }
  if (q.type === 'true_false' && q.options.length !== 2) {
    issues.push('True/false questions need exactly two options.');
  }
  if (q.time_limit_seconds < 5 || q.time_limit_seconds > 120) {
    issues.push('Time limit must be between 5 and 120 seconds.');
  }
  if (q.points < 0 || q.points > 10_000) {
    issues.push('Points must be between 0 and 10000.');
  }
  return issues;
}

export function validateQuizSet(questions: QuestionDetail[]): {
  ok: boolean;
  globalIssues: string[];
  perQuestion: Record<string, string[]>;
} {
  const globalIssues: string[] = [];
  if (questions.length === 0) globalIssues.push('Add at least one question.');
  const perQuestion: Record<string, string[]> = {};
  for (const q of questions) {
    perQuestion[q.id] = validateQuestion(toDraft(q));
  }
  const ok =
    globalIssues.length === 0 && Object.values(perQuestion).every((arr) => arr.length === 0);
  return { ok, globalIssues, perQuestion };
}
