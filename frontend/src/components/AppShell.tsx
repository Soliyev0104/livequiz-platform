import * as React from 'react';

import { Footer } from '@/components/layout/Footer';
import { Sidebar } from '@/components/layout/Sidebar';
import { TopBar } from '@/components/layout/TopBar';

interface AppShellProps {
  children: React.ReactNode;
  withSidebar?: boolean;
}

export function AppShell({ children, withSidebar = false }: AppShellProps): React.JSX.Element {
  return (
    <div className="flex min-h-screen flex-col">
      <TopBar />
      <div className="flex flex-1">
        {withSidebar && <Sidebar />}
        <main className="flex-1">{children}</main>
      </div>
      <Footer />
    </div>
  );
}
