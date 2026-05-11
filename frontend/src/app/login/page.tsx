import Link from 'next/link';
import type { Metadata } from 'next';
import * as React from 'react';

import { Logo } from '@/components/Logo';
import { AuthForm } from '@/features/auth/AuthForm';

export const metadata: Metadata = { title: 'Sign in' };

function safeNext(value: string | string[] | undefined): string {
  const v = Array.isArray(value) ? value[0] : value;
  if (v && v.startsWith('/') && !v.startsWith('//')) return v;
  return '/dashboard';
}

export default async function LoginPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}): Promise<React.JSX.Element> {
  const sp = await searchParams;
  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-8 px-4 py-12">
      <Link href="/">
        <Logo />
      </Link>
      <AuthForm mode="login" redirectTo={safeNext(sp.next)} />
    </div>
  );
}
