'use client';

import { zodResolver } from '@hookform/resolvers/zod';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { AlertCircle, Loader2 } from 'lucide-react';
import * as React from 'react';
import { useForm } from 'react-hook-form';
import { z } from 'zod';

import { DemoCredsCard } from '@/features/auth/DemoCredsCard';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { ApiError } from '@/lib/api-client';
import { useAuthStore } from '@/lib/auth';

const loginSchema = z.object({
  email: z.string().email('Enter a valid email'),
  password: z.string().min(1, 'Password is required'),
});

const registerSchema = z
  .object({
    display_name: z.string().min(1, 'Display name is required').max(80),
    email: z.string().email('Enter a valid email'),
    password: z.string().min(8, 'At least 8 characters').max(128),
    confirm: z.string(),
  })
  .refine((v) => v.password === v.confirm, {
    message: 'Passwords do not match',
    path: ['confirm'],
  });

type LoginValues = z.infer<typeof loginSchema>;
type RegisterValues = z.infer<typeof registerSchema>;

interface AuthFormProps {
  mode: 'login' | 'register';
  redirectTo?: string;
}

export function AuthForm({ mode, redirectTo = '/dashboard' }: AuthFormProps): React.JSX.Element {
  const router = useRouter();
  const login = useAuthStore((s) => s.login);
  const register = useAuthStore((s) => s.register);
  const [formError, setFormError] = React.useState<string | null>(null);

  const isRegister = mode === 'register';

  const form = useForm<RegisterValues>({
    resolver: zodResolver(isRegister ? registerSchema : loginSchema) as never,
    defaultValues: { display_name: '', email: '', password: '', confirm: '' },
  });
  const {
    register: field,
    handleSubmit,
    setValue,
    formState: { errors, isSubmitting },
  } = form;

  async function onSubmit(values: RegisterValues): Promise<void> {
    setFormError(null);
    try {
      if (isRegister) {
        await register(values.email, values.password, values.display_name);
      } else {
        await login(values.email, values.password);
      }
      router.replace(redirectTo);
    } catch (err) {
      if (err instanceof ApiError) {
        setFormError(err.message || err.code);
      } else {
        setFormError('Something went wrong. Please try again.');
      }
    }
  }

  return (
    <div className="grid w-full max-w-md gap-6">
      <Card>
        <CardHeader>
          <CardTitle className="text-2xl">{isRegister ? 'Create your account' : 'Welcome back'}</CardTitle>
          <CardDescription>
            {isRegister
              ? 'Hosts can build quizzes and run live rooms.'
              : 'Sign in to your host dashboard.'}
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit(onSubmit)} className="space-y-4" noValidate>
            {isRegister && (
              <div className="space-y-1.5">
                <Label htmlFor="display_name">Display name</Label>
                <Input id="display_name" autoComplete="name" {...field('display_name')} />
                {errors.display_name && (
                  <p className="text-sm text-destructive">{errors.display_name.message}</p>
                )}
              </div>
            )}
            <div className="space-y-1.5">
              <Label htmlFor="email">Email</Label>
              <Input id="email" type="email" autoComplete="email" {...field('email')} />
              {errors.email && <p className="text-sm text-destructive">{errors.email.message}</p>}
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="password">Password</Label>
              <Input
                id="password"
                type="password"
                autoComplete={isRegister ? 'new-password' : 'current-password'}
                {...field('password')}
              />
              {errors.password && (
                <p className="text-sm text-destructive">{errors.password.message}</p>
              )}
            </div>
            {isRegister && (
              <div className="space-y-1.5">
                <Label htmlFor="confirm">Confirm password</Label>
                <Input id="confirm" type="password" autoComplete="new-password" {...field('confirm')} />
                {errors.confirm && (
                  <p className="text-sm text-destructive">{errors.confirm.message}</p>
                )}
              </div>
            )}

            {formError && (
              <div className="flex items-start gap-2 rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive">
                <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
                <span>{formError}</span>
              </div>
            )}

            <Button type="submit" className="w-full" size="lg" disabled={isSubmitting}>
              {isSubmitting && <Loader2 className="h-4 w-4 animate-spin" />}
              {isRegister ? 'Create account' : 'Sign in'}
            </Button>
          </form>

          <p className="mt-4 text-center text-sm text-muted-foreground">
            {isRegister ? (
              <>
                Already have an account?{' '}
                <Link href="/login" className="font-medium text-primary hover:underline">
                  Sign in
                </Link>
              </>
            ) : (
              <>
                New to LiveQuiz?{' '}
                <Link href="/register" className="font-medium text-primary hover:underline">
                  Create an account
                </Link>
              </>
            )}
          </p>
        </CardContent>
      </Card>

      {!isRegister && (
        <DemoCredsCard
          onPick={(email, password) => {
            setValue('email', email);
            setValue('password', password);
          }}
        />
      )}
    </div>
  );
}
