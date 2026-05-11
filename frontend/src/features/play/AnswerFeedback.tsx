'use client';

import { motion } from 'framer-motion';
import { CheckCircle2, Clock, Loader2 } from 'lucide-react';
import * as React from 'react';

import type { MyAnswer } from '@/features/live-match/store';
import { cn } from '@/lib/utils';

export function AnswerFeedback({ answer }: { answer: MyAnswer }): React.JSX.Element {
  let tone: 'pending' | 'accepted' | 'late' = 'pending';
  if (answer.tooLate || (!answer.pending && !answer.accepted)) tone = 'late';
  else if (!answer.pending && answer.accepted) tone = 'accepted';

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      className={cn(
        'flex items-center gap-3 rounded-xl border px-4 py-3 text-sm',
        tone === 'accepted' && 'border-success/50 bg-success/10 text-success',
        tone === 'late' && 'border-destructive/50 bg-destructive/10 text-destructive',
        tone === 'pending' && 'border-border bg-card text-muted-foreground',
      )}
    >
      {tone === 'pending' && <Loader2 className="h-5 w-5 animate-spin" />}
      {tone === 'accepted' && <CheckCircle2 className="h-5 w-5" />}
      {tone === 'late' && <Clock className="h-5 w-5" />}
      <div>
        {tone === 'pending' && <p className="font-medium">Answer locked in — waiting for the server…</p>}
        {tone === 'accepted' && (
          <p className="font-medium">
            Answer accepted
            {typeof answer.scoreAwarded === 'number' && answer.scoreAwarded > 0
              ? ` · +${answer.scoreAwarded.toLocaleString()} points`
              : ''}
            {typeof answer.responseTimeMs === 'number' ? ` · ${(answer.responseTimeMs / 1000).toFixed(2)}s` : ''}
          </p>
        )}
        {tone === 'late' && <p className="font-medium">Too late — your answer may not count.</p>}
      </div>
    </motion.div>
  );
}
