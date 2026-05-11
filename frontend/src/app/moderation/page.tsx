import type { Metadata } from 'next';
import * as React from 'react';

import { ModerationView } from '@/features/moderation/ModerationView';

export const metadata: Metadata = { title: 'Moderation' };

export default function ModerationPage(): React.JSX.Element {
  return <ModerationView />;
}
