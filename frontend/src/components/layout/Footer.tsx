import Link from 'next/link';
import * as React from 'react';

export function Footer(): React.JSX.Element {
  return (
    <footer className="border-t border-border/70">
      <div className="mx-auto flex max-w-7xl flex-col items-center justify-between gap-2 px-4 py-6 text-sm text-muted-foreground sm:flex-row sm:px-6">
        <p>LiveQuiz — real-time multiplayer quiz platform.</p>
        <nav className="flex items-center gap-4">
          <Link href="/" className="hover:text-foreground">
            Home
          </Link>
          <Link href="/join" className="hover:text-foreground">
            Join a room
          </Link>
          <a href="/api/docs" className="hover:text-foreground">
            API docs
          </a>
        </nav>
      </div>
    </footer>
  );
}
