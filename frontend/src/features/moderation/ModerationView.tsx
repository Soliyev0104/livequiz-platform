'use client';

import { Ban, Gavel, Loader2, ShieldOff, ShieldQuestion, VolumeX } from 'lucide-react';
import * as React from 'react';
import { toast } from 'sonner';

import { AppShell } from '@/components/AppShell';
import { AuthGuard } from '@/components/AuthGuard';
import { EmptyState } from '@/components/EmptyState';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Textarea } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Skeleton } from '@/components/ui/skeleton';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { useDecideReport, useReports } from '@/features/moderation/hooks';
import { ApiError } from '@/lib/api-client';
import { formatRelativeTime } from '@/lib/utils';
import type { DecisionAction, ReportQueueItem, ReportStatus } from '@/lib/types';

const STATUS_TABS: { value: ReportStatus; label: string }[] = [
  { value: 'pending', label: 'Pending' },
  { value: 'action_taken', label: 'Actioned' },
  { value: 'dismissed', label: 'Dismissed' },
];

const DECISION_META: Record<DecisionAction, { label: string; icon: React.ReactNode; description: string }> = {
  dismiss: { label: 'Dismiss', icon: <ShieldOff className="h-4 w-4" />, description: 'No action — the report is closed.' },
  hide: { label: 'Hide content', icon: <ShieldQuestion className="h-4 w-4" />, description: 'Hide the reported content.' },
  mute: { label: 'Mute player', icon: <VolumeX className="h-4 w-4" />, description: 'Prevent the player from chatting/answering.' },
  ban: { label: 'Ban player', icon: <Ban className="h-4 w-4" />, description: 'Remove the player from the platform.' },
};

function targetLabel(item: ReportQueueItem): string {
  const t = item.target;
  if (!t) {
    const r = item.report;
    if (r.target_user_id) return `User #${r.target_user_id}`;
    if (r.target_quiz_set_id) return `Quiz #${r.target_quiz_set_id}`;
    if (r.room_id) return `Room #${r.room_id}`;
    return 'Unknown';
  }
  return t.label ? `${t.label}` : `${t.kind} #${t.id}`;
}

function DecisionDialog({
  item,
  onClose,
}: {
  item: ReportQueueItem | null;
  onClose: () => void;
}): React.JSX.Element {
  const decide = useDecideReport();
  const [decision, setDecision] = React.useState<DecisionAction>('dismiss');
  const [reason, setReason] = React.useState('');

  React.useEffect(() => {
    if (item) {
      setDecision('dismiss');
      setReason('');
    }
    // Only reset the form when a *different* report is opened.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [item?.report.id]);

  const open = !!item;

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Review report</DialogTitle>
          <DialogDescription>
            {item ? `Report #${item.report.id} · target: ${targetLabel(item)}` : ''}
          </DialogDescription>
        </DialogHeader>
        {item && (
          <div className="space-y-4">
            <div className="rounded-lg border border-border/60 bg-muted/30 p-3 text-sm">
              <p className="font-medium">{item.report.reason}</p>
              {item.report.details && <p className="mt-1 text-muted-foreground">{item.report.details}</p>}
              <p className="mt-2 text-xs text-muted-foreground">
                Reported {formatRelativeTime(item.report.created_at)}
                {item.report.reporter_user_id ? ` by user #${item.report.reporter_user_id}` : ' by a guest'}
              </p>
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="decision">Decision</Label>
              <Select value={decision} onValueChange={(v) => setDecision(v as DecisionAction)}>
                <SelectTrigger id="decision">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {(Object.keys(DECISION_META) as DecisionAction[]).map((d) => (
                    <SelectItem key={d} value={d}>
                      <span className="flex items-center gap-2">
                        {DECISION_META[d].icon}
                        {DECISION_META[d].label}
                      </span>
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <p className="text-xs text-muted-foreground">{DECISION_META[decision].description}</p>
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="reason">Reason (optional)</Label>
              <Textarea
                id="reason"
                rows={2}
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                placeholder="Internal note for the audit trail"
                maxLength={500}
              />
            </div>
          </div>
        )}
        <DialogFooter>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button
            variant={decision === 'ban' || decision === 'mute' ? 'destructive' : 'default'}
            disabled={!item || decide.isPending}
            onClick={async () => {
              if (!item) return;
              try {
                await decide.mutateAsync({
                  reportId: item.report.id,
                  body: { decision, reason: reason.trim() ? reason.trim() : null },
                });
                toast.success(`Report ${DECISION_META[decision].label.toLowerCase()}ed`);
                onClose();
              } catch (err) {
                toast.error(err instanceof ApiError ? err.message : 'Could not record the decision');
              }
            }}
          >
            {decide.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
            Confirm decision
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function ReportsTable({
  status,
  onReview,
}: {
  status: ReportStatus;
  onReview: (item: ReportQueueItem) => void;
}): React.JSX.Element {
  const { data, isLoading, isError } = useReports(status);

  if (isLoading) {
    return (
      <div className="space-y-2">
        {Array.from({ length: 4 }).map((_, i) => (
          <Skeleton key={i} className="h-14 w-full rounded-lg" />
        ))}
      </div>
    );
  }
  if (isError) {
    return <EmptyState title="Could not load the queue" description="Please refresh the page." />;
  }
  const items = data?.items ?? [];
  if (items.length === 0) {
    return (
      <EmptyState
        icon={<Gavel className="h-10 w-10" />}
        title={status === 'pending' ? 'Queue is clear' : 'Nothing here'}
        description={
          status === 'pending'
            ? 'There are no pending reports to review.'
            : 'No reports with this status.'
        }
      />
    );
  }
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Reason</TableHead>
          <TableHead>Target</TableHead>
          <TableHead>Reported</TableHead>
          <TableHead>Status</TableHead>
          <TableHead className="text-right">Action</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {items.map((item) => (
          <TableRow key={item.report.id}>
            <TableCell className="max-w-[20rem]">
              <div className="truncate font-medium">{item.report.reason}</div>
              {item.report.details && (
                <div className="truncate text-xs text-muted-foreground">{item.report.details}</div>
              )}
            </TableCell>
            <TableCell>
              <Badge variant="muted" className="capitalize">
                {item.target?.kind ?? 'item'}
              </Badge>{' '}
              <span className="text-sm">{targetLabel(item)}</span>
            </TableCell>
            <TableCell className="text-sm text-muted-foreground">
              {formatRelativeTime(item.report.created_at)}
            </TableCell>
            <TableCell>
              <Badge
                variant={
                  item.report.status === 'pending'
                    ? 'default'
                    : item.report.status === 'dismissed'
                      ? 'muted'
                      : 'destructive'
                }
                className="capitalize"
              >
                {item.report.status.replace('_', ' ')}
              </Badge>
            </TableCell>
            <TableCell className="text-right">
              <Button size="sm" variant={status === 'pending' ? 'default' : 'outline'} onClick={() => onReview(item)}>
                {status === 'pending' ? 'Review' : 'Details'}
              </Button>
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

function ModerationInner(): React.JSX.Element {
  const [status, setStatus] = React.useState<ReportStatus>('pending');
  const [active, setActive] = React.useState<ReportQueueItem | null>(null);

  return (
    <div className="mx-auto w-full max-w-5xl px-4 py-8 sm:px-6">
      <div className="mb-6">
        <h1 className="text-2xl font-semibold tracking-tight">Moderation queue</h1>
        <p className="text-muted-foreground">Review reported players, quizzes, and rooms.</p>
      </div>

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-base">Reports</CardTitle>
        </CardHeader>
        <CardContent>
          <Tabs value={status} onValueChange={(v) => setStatus(v as ReportStatus)}>
            <TabsList>
              {STATUS_TABS.map((t) => (
                <TabsTrigger key={t.value} value={t.value}>
                  {t.label}
                </TabsTrigger>
              ))}
            </TabsList>
            {STATUS_TABS.map((t) => (
              <TabsContent key={t.value} value={t.value}>
                <ReportsTable status={t.value} onReview={setActive} />
              </TabsContent>
            ))}
          </Tabs>
        </CardContent>
      </Card>

      <DecisionDialog item={active} onClose={() => setActive(null)} />
    </div>
  );
}

export function ModerationView(): React.JSX.Element {
  return (
    <AuthGuard requireRole={['moderator', 'admin']}>
      <AppShell withSidebar>
        <ModerationInner />
      </AppShell>
    </AuthGuard>
  );
}
