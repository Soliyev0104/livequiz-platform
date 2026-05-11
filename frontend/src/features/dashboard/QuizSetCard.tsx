'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { ListChecks, Loader2, PlayCircle, Pencil } from 'lucide-react';
import * as React from 'react';
import { toast } from 'sonner';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardFooter, CardHeader, CardTitle } from '@/components/ui/card';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import { rememberRoom } from '@/features/dashboard/recent-rooms';
import { useCreateRoom } from '@/features/room-lobby/hooks';
import { saveHostRoomSession } from '@/features/room-lobby/host-session';
import { ApiError } from '@/lib/api-client';
import type { QuizSetSummary } from '@/lib/types';

export function QuizSetCard({ quiz }: { quiz: QuizSetSummary }): React.JSX.Element {
  const router = useRouter();
  const createRoom = useCreateRoom();

  async function host(): Promise<void> {
    try {
      const room = await createRoom.mutateAsync({ quiz_set_id: quiz.id });
      saveHostRoomSession({
        code: room.code,
        roomId: room.room_id,
        hostWsUrl: room.host_ws_url,
        quizSetId: quiz.id,
        quizTitle: quiz.title,
      });
      rememberRoom({ code: room.code, quizTitle: quiz.title, createdAt: new Date().toISOString() });
      router.push(`/host/rooms/${room.code}`);
    } catch (err) {
      const msg = err instanceof ApiError ? err.message : 'Could not create the room';
      toast.error(msg);
    }
  }

  const canHost = quiz.is_published && quiz.question_count > 0;

  return (
    <Card className="flex flex-col">
      <CardHeader className="pb-3">
        <div className="flex items-start justify-between gap-2">
          <CardTitle className="text-base leading-snug">{quiz.title}</CardTitle>
          <Badge variant={quiz.is_published ? 'success' : 'muted'}>
            {quiz.is_published ? 'Published' : 'Draft'}
          </Badge>
        </div>
      </CardHeader>
      <CardContent className="flex-1 pb-3 text-sm text-muted-foreground">
        <div className="flex items-center gap-1.5">
          <ListChecks className="h-4 w-4" />
          {quiz.question_count} {quiz.question_count === 1 ? 'question' : 'questions'}
          <span className="text-muted-foreground/60">· v{quiz.version}</span>
        </div>
      </CardContent>
      <CardFooter className="gap-2">
        <Button variant="outline" size="sm" asChild className="flex-1">
          <Link href={`/quiz-sets/${quiz.id}/edit`} className="gap-1.5">
            <Pencil className="h-4 w-4" /> Edit
          </Link>
        </Button>
        {canHost ? (
          <Button size="sm" className="flex-1" onClick={host} disabled={createRoom.isPending}>
            {createRoom.isPending ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <PlayCircle className="h-4 w-4" />
            )}
            Host
          </Button>
        ) : (
          <Tooltip>
            <TooltipTrigger asChild>
              <span className="flex-1">
                <Button size="sm" className="w-full" disabled>
                  <PlayCircle className="h-4 w-4" /> Host
                </Button>
              </span>
            </TooltipTrigger>
            <TooltipContent>Publish the quiz (with at least one question) to host a room.</TooltipContent>
          </Tooltip>
        )}
      </CardFooter>
    </Card>
  );
}
