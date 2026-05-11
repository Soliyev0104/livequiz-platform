import type { Metadata } from 'next';
import * as React from 'react';

import { JoinView } from '@/features/play/JoinView';

export const metadata: Metadata = { title: 'Join a room' };

function firstParam(value: string | string[] | undefined): string | undefined {
  const v = Array.isArray(value) ? value[0] : value;
  return v ? v.trim().toUpperCase() : undefined;
}

export default async function JoinPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}): Promise<React.JSX.Element> {
  const sp = await searchParams;
  return <JoinView defaultCode={firstParam(sp.code)} />;
}
