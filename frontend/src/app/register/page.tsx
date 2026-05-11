import Link from 'next/link';
import type { Metadata } from 'next';
import * as React from 'react';

import { Logo } from '@/components/Logo';
import { AuthForm } from '@/features/auth/AuthForm';

export const metadata: Metadata = { title: 'Create account' };

export default function RegisterPage(): React.JSX.Element {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-8 px-4 py-12">
      <Link href="/">
        <Logo />
      </Link>
      <AuthForm mode="register" redirectTo="/dashboard" />
    </div>
  );
}
