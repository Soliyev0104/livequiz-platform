import * as React from 'react';

import { cn } from '@/lib/utils';

interface EmptyStateProps {
  icon?: React.ReactNode;
  title: string;
  description?: string;
  action?: React.ReactNode;
  className?: string;
}

export function EmptyState({
  icon,
  title,
  description,
  action,
  className,
}: EmptyStateProps): React.JSX.Element {
  return (
    <div
      className={cn(
        'flex flex-col items-center justify-center gap-3 rounded-xl border border-dashed border-border/70 bg-card/40 px-6 py-12 text-center',
        className,
      )}
    >
      {icon && <div className="text-muted-foreground">{icon}</div>}
      <h3 className="text-lg font-semibold">{title}</h3>
      {description && <p className="max-w-md text-sm text-muted-foreground">{description}</p>}
      {action && <div className="pt-1">{action}</div>}
    </div>
  );
}
