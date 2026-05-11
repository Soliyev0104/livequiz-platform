'use client';

import { QRCodeSVG } from 'qrcode.react';
import { Check, Copy } from 'lucide-react';
import * as React from 'react';
import { toast } from 'sonner';

import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';

export function RoomCodeCard({ code }: { code: string }): React.JSX.Element {
  const [copied, setCopied] = React.useState(false);
  const joinUrl =
    typeof window !== 'undefined' ? `${window.location.origin}/join?code=${code}` : `/join?code=${code}`;

  async function copy(value: string, label: string): Promise<void> {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      toast.success(`${label} copied`);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      toast.error('Could not copy to clipboard');
    }
  }

  return (
    <Card>
      <CardContent className="flex flex-col items-center gap-5 p-6 sm:flex-row sm:items-center sm:justify-between">
        <div className="text-center sm:text-left">
          <p className="text-xs font-medium uppercase tracking-widest text-muted-foreground">Room code</p>
          <div className="mt-1 flex items-center justify-center gap-3 sm:justify-start">
            <span className="font-mono text-4xl font-bold tracking-[0.3em] sm:text-5xl">{code}</span>
            <Button
              variant="ghost"
              size="icon"
              aria-label="Copy room code"
              onClick={() => copy(code, 'Room code')}
            >
              {copied ? <Check className="h-5 w-5 text-success" /> : <Copy className="h-5 w-5" />}
            </Button>
          </div>
          <button
            type="button"
            onClick={() => copy(joinUrl, 'Join link')}
            className="mt-2 text-sm text-muted-foreground underline-offset-2 hover:text-foreground hover:underline"
          >
            Copy the join link
          </button>
        </div>
        <div className="rounded-lg bg-white p-3">
          <QRCodeSVG value={joinUrl} size={120} includeMargin={false} />
        </div>
      </CardContent>
    </Card>
  );
}
