import type { Metadata } from 'next';
import * as React from 'react';

import { PlayView } from '@/features/play/PlayView';

export const metadata: Metadata = { title: 'Play' };

export default async function PlayPage({
  params,
}: {
  params: Promise<{ code: string }>;
}): Promise<React.JSX.Element> {
  const { code } = await params;
  return <PlayView code={code} />;
}
