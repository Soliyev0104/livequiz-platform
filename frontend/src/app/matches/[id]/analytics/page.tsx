import type { Metadata } from 'next';
import * as React from 'react';

import { AnalyticsView } from '@/features/analytics/AnalyticsView';

export const metadata: Metadata = { title: 'Match analytics' };

export default async function MatchAnalyticsPage({
  params,
}: {
  params: Promise<{ id: string }>;
}): Promise<React.JSX.Element> {
  const { id } = await params;
  return <AnalyticsView matchId={id} />;
}
