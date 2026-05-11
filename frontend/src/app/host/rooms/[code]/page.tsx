import type { Metadata } from 'next';
import * as React from 'react';

import { HostRoomView } from '@/features/room-lobby/HostRoomView';

export const metadata: Metadata = { title: 'Host room' };

export default async function HostRoomPage({
  params,
}: {
  params: Promise<{ code: string }>;
}): Promise<React.JSX.Element> {
  const { code } = await params;
  return <HostRoomView code={code} />;
}
