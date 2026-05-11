'use client';

import { useTheme } from 'next-themes';
import { Toaster as SonnerToaster } from 'sonner';

type ToasterProps = React.ComponentProps<typeof SonnerToaster>;

export function Toaster(props: ToasterProps): React.JSX.Element {
  const { theme = 'dark' } = useTheme();
  return (
    <SonnerToaster
      theme={theme as ToasterProps['theme']}
      richColors
      closeButton
      position="top-right"
      toastOptions={{
        classNames: {
          toast: 'group toast border-border bg-card text-card-foreground shadow-lg',
          description: 'text-muted-foreground',
        },
      }}
      {...props}
    />
  );
}
