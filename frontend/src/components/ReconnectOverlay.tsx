'use client';

import { Loader2, WifiOff } from 'lucide-react';
import * as React from 'react';

interface ReconnectOverlayProps {
  /** Whether the socket is currently reconnecting/closed. */
  active: boolean;
  /** True if a question deadline elapsed while disconnected. */
  deadlineMissed?: boolean;
}

export function ReconnectOverlay({ active, deadlineMissed }: ReconnectOverlayProps): React.JSX.Element | null {
  if (!active) return null;
  return (
    <div
      role="status"
      aria-live="polite"
      className="pointer-events-none fixed inset-x-0 top-0 z-50 flex justify-center p-4"
    >
      <div className="pointer-events-auto flex items-center gap-3 rounded-full border border-border bg-card/95 px-4 py-2 text-sm shadow-lg backdrop-blur">
        {deadlineMissed ? (
          <>
            <WifiOff className="h-4 w-4 text-destructive" />
            <span>Connection lost — your answer may not count.</span>
          </>
        ) : (
          <>
            <Loader2 className="h-4 w-4 animate-spin text-primary" />
            <span>Reconnecting…</span>
          </>
        )}
      </div>
    </div>
  );
}
