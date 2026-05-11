'use client';

import { useRouter } from 'next/navigation';
import { ArrowLeft } from 'lucide-react';
import Link from 'next/link';
import * as React from 'react';
import { toast } from 'sonner';

import { AppShell } from '@/components/AppShell';
import { AuthGuard } from '@/components/AuthGuard';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { QuizMetaForm } from '@/features/quiz-builder/QuizMetaForm';
import { useCreateQuizSet } from '@/features/quiz-builder/hooks';
import { ApiError } from '@/lib/api-client';

function NewQuizInner(): React.JSX.Element {
  const router = useRouter();
  const create = useCreateQuizSet();

  return (
    <div className="mx-auto w-full max-w-2xl px-4 py-8 sm:px-6">
      <Button variant="ghost" size="sm" asChild className="mb-4 -ml-2">
        <Link href="/dashboard" className="gap-1.5">
          <ArrowLeft className="h-4 w-4" /> Back to dashboard
        </Link>
      </Button>
      <Card>
        <CardHeader>
          <CardTitle className="text-2xl">Create a quiz set</CardTitle>
          <CardDescription>Start with the basics — you will add questions next.</CardDescription>
        </CardHeader>
        <CardContent>
          <QuizMetaForm
            submitLabel="Create and add questions"
            submitting={create.isPending}
            onSubmit={async (values) => {
              try {
                const summary = await create.mutateAsync(values);
                router.replace(`/quiz-sets/${summary.id}/edit`);
              } catch (err) {
                toast.error(err instanceof ApiError ? err.message : 'Could not create the quiz');
              }
            }}
          />
        </CardContent>
      </Card>
    </div>
  );
}

export function NewQuizView(): React.JSX.Element {
  return (
    <AuthGuard requireRole={['host', 'admin']}>
      <AppShell>
        <NewQuizInner />
      </AppShell>
    </AuthGuard>
  );
}
