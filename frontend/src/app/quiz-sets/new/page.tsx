import type { Metadata } from 'next';
import * as React from 'react';

import { NewQuizView } from '@/features/quiz-builder/NewQuizView';

export const metadata: Metadata = { title: 'New quiz' };

export default function NewQuizPage(): React.JSX.Element {
  return <NewQuizView />;
}
