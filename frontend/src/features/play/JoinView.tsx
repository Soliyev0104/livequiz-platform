'use client';

import { zodResolver } from '@hookform/resolvers/zod';
import { useRouter } from 'next/navigation';
import { Loader2, LogIn } from 'lucide-react';
import * as React from 'react';
import { useForm } from 'react-hook-form';
import { toast } from 'sonner';
import { z } from 'zod';

import { AppShell } from '@/components/AppShell';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { useJoinRoom } from '@/features/play/hooks';
import { savePlayerRoomSession } from '@/features/play/player-session';
import { ApiError } from '@/lib/api-client';

const schema = z.object({
  code: z
    .string()
    .min(4, 'Enter the room code')
    .max(12)
    .transform((v) => v.trim().toUpperCase()),
  nickname: z.string().min(1, 'Choose a nickname').max(60),
});

type Values = z.input<typeof schema>;

function JoinInner({ defaultCode }: { defaultCode?: string }): React.JSX.Element {
  const router = useRouter();
  const join = useJoinRoom();
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: { code: defaultCode ?? '', nickname: '' },
  });

  return (
    <div className="mx-auto flex w-full max-w-md flex-col gap-6 px-4 py-12 sm:px-6">
      <div className="text-center">
        <h1 className="text-3xl font-semibold tracking-tight">Join a room</h1>
        <p className="mt-1 text-muted-foreground">Enter the code your host shared with you.</p>
      </div>
      <Card>
        <CardHeader>
          <CardTitle className="text-xl">Room details</CardTitle>
          <CardDescription>No account needed — you can play as a guest.</CardDescription>
        </CardHeader>
        <CardContent>
          <form
            noValidate
            className="space-y-4"
            onSubmit={handleSubmit(async (values) => {
              const code = values.code.trim().toUpperCase();
              try {
                const res = await join.mutateAsync({
                  code,
                  body: { nickname: values.nickname.trim() },
                });
                savePlayerRoomSession({
                  code: res.code,
                  roomId: res.room_id,
                  participantId: res.participant_id,
                  nickname: res.nickname,
                  participantToken: res.participant_token,
                  wsUrl: res.ws_url,
                });
                router.replace(`/play/${res.code}`);
              } catch (err) {
                toast.error(err instanceof ApiError ? err.message : 'Could not join the room');
              }
            })}
          >
            <div className="space-y-1.5">
              <Label htmlFor="code">Room code</Label>
              <Input
                id="code"
                autoComplete="off"
                autoCapitalize="characters"
                className="font-mono text-lg uppercase tracking-[0.3em]"
                placeholder="ABCD12"
                {...register('code')}
              />
              {errors.code && <p className="text-sm text-destructive">{errors.code.message}</p>}
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="nickname">Nickname</Label>
              <Input id="nickname" autoComplete="off" placeholder="Avenger" {...register('nickname')} />
              {errors.nickname && <p className="text-sm text-destructive">{errors.nickname.message}</p>}
            </div>
            <Button type="submit" size="lg" className="w-full" disabled={join.isPending}>
              {join.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <LogIn className="h-4 w-4" />}
              Join room
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}

export function JoinView({ defaultCode }: { defaultCode?: string }): React.JSX.Element {
  return (
    <AppShell>
      <JoinInner defaultCode={defaultCode} />
    </AppShell>
  );
}
