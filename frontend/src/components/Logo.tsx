import Link from 'next/link';
import * as React from 'react';

import { cn } from '@/lib/utils';

export function Logo({ href = '/', className }: { href?: string; className?: string }): React.JSX.Element {
  return (
    <Link href={href} className={cn('flex items-center gap-2 font-semibold', className)}>
      <span className="grid h-8 w-8 place-items-center rounded-lg bg-primary text-primary-foreground shadow">
        <span aria-hidden className="text-base font-bold">
          L
        </span>
      </span>
      <span className="text-lg tracking-tight">
        Live<span className="text-primary">Quiz</span>
      </span>
    </Link>
  );
}
