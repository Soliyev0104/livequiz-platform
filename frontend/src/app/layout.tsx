import type { Metadata, Viewport } from 'next';

import { Providers } from './providers';
import '@/styles/globals.css';

export const metadata: Metadata = {
  title: {
    default: 'LiveQuiz',
    template: '%s · LiveQuiz',
  },
  description: 'Host real-time quizzes with live leaderboards.',
  applicationName: 'LiveQuiz',
};

export const viewport: Viewport = {
  themeColor: '#0b1120',
  width: 'device-width',
  initialScale: 1,
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}): React.JSX.Element {
  return (
    <html lang="en" className="dark" suppressHydrationWarning>
      <body className="min-h-screen bg-background text-foreground antialiased">
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
