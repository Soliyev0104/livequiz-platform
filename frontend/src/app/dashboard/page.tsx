import type { Metadata } from 'next';
import * as React from 'react';

import { DashboardView } from '@/features/dashboard/DashboardView';

export const metadata: Metadata = { title: 'Dashboard' };

export default function DashboardPage(): React.JSX.Element {
  return <DashboardView />;
}
