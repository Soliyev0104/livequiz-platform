'use client';

import Link from 'next/link';
import { ArrowLeft, FileQuestion, Loader2, Settings2 } from 'lucide-react';
import * as React from 'react';
import { toast } from 'sonner';

import { AppShell } from '@/components/AppShell';
import { AuthGuard } from '@/components/AuthGuard';
import { EmptyState } from '@/components/EmptyState';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Skeleton } from '@/components/ui/skeleton';
import { QuestionEditor } from '@/features/quiz-builder/QuestionEditor';
import { QuestionList } from '@/features/quiz-builder/QuestionList';
import { QuizMetaForm } from '@/features/quiz-builder/QuizMetaForm';
import { ValidationPanel } from '@/features/quiz-builder/ValidationPanel';
import {
  useAddQuestion,
  usePublishQuizSet,
  useQuizSet,
  useUpdateQuestion,
  useUpdateQuizSet,
} from '@/features/quiz-builder/hooks';
import { validateQuizSet } from '@/features/quiz-builder/validation';
import { ApiError } from '@/lib/api-client';
import type { QuestionCreate } from '@/lib/types';

const NEW_QUESTION: QuestionCreate = {
  body: 'New question',
  type: 'single_choice',
  time_limit_seconds: 20,
  points: 1000,
  explanation: null,
  options: [
    { position: 1, body: 'Option 1', is_correct: true },
    { position: 2, body: 'Option 2', is_correct: false },
  ],
};

function BuilderInner({ quizId }: { quizId: string }): React.JSX.Element {
  const { data: quiz, isLoading, isError, error } = useQuizSet(quizId);
  const updateQuestion = useUpdateQuestion(quizId);
  const addQuestion = useAddQuestion(quizId);
  const updateQuiz = useUpdateQuizSet(quizId);
  const publish = usePublishQuizSet(quizId);

  const [selectedId, setSelectedId] = React.useState<string | null>(null);
  const [metaOpen, setMetaOpen] = React.useState(false);
  const [publishError, setPublishError] = React.useState<string | null>(null);

  const questions = React.useMemo(
    () => (quiz?.questions ?? []).slice().sort((a, b) => a.position - b.position),
    [quiz?.questions],
  );

  React.useEffect(() => {
    if (questions.length === 0) {
      setSelectedId(null);
      return;
    }
    if (!selectedId || !questions.some((q) => q.id === selectedId)) {
      setSelectedId(questions[0].id);
    }
  }, [questions, selectedId]);

  if (isLoading) {
    return (
      <div className="mx-auto w-full max-w-7xl px-4 py-8 sm:px-6">
        <Skeleton className="mb-6 h-9 w-72" />
        <div className="grid gap-4 lg:grid-cols-[280px_1fr_300px]">
          <Skeleton className="h-[60vh] w-full rounded-xl" />
          <Skeleton className="h-[60vh] w-full rounded-xl" />
          <Skeleton className="h-[40vh] w-full rounded-xl" />
        </div>
      </div>
    );
  }

  if (isError || !quiz) {
    const msg = error instanceof ApiError ? error.message : 'Could not load this quiz set.';
    return (
      <div className="mx-auto w-full max-w-2xl px-4 py-16">
        <EmptyState title="Quiz unavailable" description={msg} action={
          <Button asChild variant="outline"><Link href="/dashboard">Back to dashboard</Link></Button>
        } />
      </div>
    );
  }

  if (quiz.questions === null) {
    return (
      <div className="mx-auto w-full max-w-2xl px-4 py-16">
        <EmptyState
          title="You do not own this quiz"
          description="Only the owner can edit a quiz set."
          action={<Button asChild variant="outline"><Link href="/dashboard">Back to dashboard</Link></Button>}
        />
      </div>
    );
  }

  const validation = validateQuizSet(questions);
  const invalidIds = new Set(
    Object.entries(validation.perQuestion)
      .filter(([, issues]) => issues.length > 0)
      .map(([id]) => id),
  );
  const selectedIndex = selectedId ? questions.findIndex((q) => q.id === selectedId) : -1;
  const selectedQuestion = selectedIndex >= 0 ? questions[selectedIndex] : null;

  async function handleReorder(movedQuestionId: string, newPosition: number): Promise<void> {
    try {
      await updateQuestion.mutateAsync({ questionId: movedQuestionId, body: { position: newPosition } });
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : 'Could not reorder questions');
    }
  }

  async function handleAdd(): Promise<void> {
    try {
      const created = await addQuestion.mutateAsync(NEW_QUESTION);
      setSelectedId(created.id);
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : 'Could not add a question');
    }
  }

  async function handlePublish(): Promise<void> {
    setPublishError(null);
    if (!validation.ok) {
      setPublishError('Resolve the checklist items before publishing.');
      return;
    }
    try {
      await publish.mutateAsync();
      toast.success('Quiz published');
    } catch (err) {
      setPublishError(err instanceof ApiError ? err.message : 'Publish failed');
    }
  }

  return (
    <div className="mx-auto w-full max-w-7xl px-4 py-6 sm:px-6">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <Button variant="ghost" size="icon" asChild>
            <Link href="/dashboard" aria-label="Back to dashboard">
              <ArrowLeft className="h-4 w-4" />
            </Link>
          </Button>
          <div>
            <h1 className="text-xl font-semibold leading-tight">{quiz.title}</h1>
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <Badge variant={quiz.is_published ? 'success' : 'muted'}>
                {quiz.is_published ? 'Published' : 'Draft'}
              </Badge>
              <span>{quiz.visibility}</span>
              {quiz.tags.length > 0 && <span>· {quiz.tags.join(', ')}</span>}
            </div>
          </div>
        </div>
        <Button variant="outline" size="sm" onClick={() => setMetaOpen(true)}>
          <Settings2 className="h-4 w-4" /> Quiz settings
        </Button>
      </div>

      <div className="grid gap-4 lg:grid-cols-[280px_minmax(0,1fr)_300px]">
        <div className="rounded-xl border bg-card p-3 lg:h-[calc(100vh-12rem)]">
          <QuestionList
            questions={questions}
            selectedId={selectedId}
            invalidIds={invalidIds}
            onSelect={setSelectedId}
            onReorder={handleReorder}
            onAdd={handleAdd}
            adding={addQuestion.isPending}
          />
        </div>

        <div className="lg:h-[calc(100vh-12rem)]">
          {selectedQuestion ? (
            <QuestionEditor
              key={selectedQuestion.id}
              quizId={quizId}
              question={selectedQuestion}
              index={selectedIndex}
              onDeleted={() => setSelectedId(null)}
            />
          ) : (
            <EmptyState
              icon={<FileQuestion className="h-10 w-10" />}
              title="No question selected"
              description="Add a question or pick one from the list to start editing."
              action={
                <Button onClick={handleAdd} disabled={addQuestion.isPending}>
                  {addQuestion.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
                  Add question
                </Button>
              }
            />
          )}
        </div>

        <ValidationPanel
          quiz={quiz}
          ok={validation.ok}
          globalIssues={validation.globalIssues}
          perQuestion={validation.perQuestion}
          selectedQuestionId={selectedId}
          selectedIndex={selectedIndex >= 0 ? selectedIndex : null}
          publishing={publish.isPending}
          publishError={publishError}
          onPublish={handlePublish}
        />
      </div>

      <Dialog open={metaOpen} onOpenChange={setMetaOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Quiz settings</DialogTitle>
            <DialogDescription>Update the title, description, visibility, and tags.</DialogDescription>
          </DialogHeader>
          <QuizMetaForm
            initial={{
              title: quiz.title,
              description: quiz.description,
              visibility: quiz.visibility,
              tags: quiz.tags,
            }}
            submitLabel="Save changes"
            submitting={updateQuiz.isPending}
            onCancel={() => setMetaOpen(false)}
            onSubmit={async (values) => {
              try {
                await updateQuiz.mutateAsync(values);
                setMetaOpen(false);
                toast.success('Quiz updated');
              } catch (err) {
                toast.error(err instanceof ApiError ? err.message : 'Could not update the quiz');
              }
            }}
          />
        </DialogContent>
      </Dialog>
    </div>
  );
}

export function QuizBuilderView({ quizId }: { quizId: string }): React.JSX.Element {
  return (
    <AuthGuard requireRole={['host', 'admin']}>
      <AppShell>
        <BuilderInner quizId={quizId} />
      </AppShell>
    </AuthGuard>
  );
}
