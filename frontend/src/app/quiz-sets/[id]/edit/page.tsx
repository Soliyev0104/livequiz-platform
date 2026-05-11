import type { Metadata } from 'next';
import * as React from 'react';

import { QuizBuilderView } from '@/features/quiz-builder/QuizBuilderView';

export const metadata: Metadata = { title: 'Quiz builder' };

export default async function QuizEditPage({
  params,
}: {
  params: Promise<{ id: string }>;
}): Promise<React.JSX.Element> {
  const { id } = await params;
  return <QuizBuilderView quizId={id} />;
}
