'use client';

import { zodResolver } from '@hookform/resolvers/zod';
import { Loader2 } from 'lucide-react';
import * as React from 'react';
import { Controller, useForm } from 'react-hook-form';
import { z } from 'zod';

import { Button } from '@/components/ui/button';
import { Input, Textarea } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import type { Visibility } from '@/lib/types';

const schema = z.object({
  title: z.string().min(1, 'Title is required').max(160),
  description: z.string().max(4000).optional(),
  visibility: z.enum(['private', 'unlisted', 'public']),
  tags: z.string().optional(),
});

export type QuizMetaValues = z.infer<typeof schema>;

export interface QuizMetaInitial {
  title: string;
  description: string | null;
  visibility: Visibility;
  tags: string[];
}

interface QuizMetaFormProps {
  initial?: Partial<QuizMetaInitial>;
  submitLabel: string;
  submitting?: boolean;
  onSubmit: (values: {
    title: string;
    description: string | null;
    visibility: Visibility;
    tags: string[];
  }) => void | Promise<void>;
  onCancel?: () => void;
}

export function parseTags(input: string | undefined): string[] {
  if (!input) return [];
  return Array.from(
    new Set(
      input
        .split(',')
        .map((t) => t.trim().toLowerCase())
        .filter(Boolean)
        .slice(0, 20),
    ),
  );
}

export function QuizMetaForm({
  initial,
  submitLabel,
  submitting,
  onSubmit,
  onCancel,
}: QuizMetaFormProps): React.JSX.Element {
  const {
    register,
    handleSubmit,
    control,
    formState: { errors },
  } = useForm<QuizMetaValues>({
    resolver: zodResolver(schema),
    defaultValues: {
      title: initial?.title ?? '',
      description: initial?.description ?? '',
      visibility: initial?.visibility ?? 'private',
      tags: (initial?.tags ?? []).join(', '),
    },
  });

  return (
    <form
      onSubmit={handleSubmit(async (v) => {
        await onSubmit({
          title: v.title.trim(),
          description: v.description?.trim() ? v.description.trim() : null,
          visibility: v.visibility,
          tags: parseTags(v.tags),
        });
      })}
      className="space-y-4"
      noValidate
    >
      <div className="space-y-1.5">
        <Label htmlFor="title">Title</Label>
        <Input id="title" placeholder="Computer Networks Quiz" {...register('title')} />
        {errors.title && <p className="text-sm text-destructive">{errors.title.message}</p>}
      </div>

      <div className="space-y-1.5">
        <Label htmlFor="description">Description</Label>
        <Textarea
          id="description"
          rows={3}
          placeholder="What is this quiz about?"
          {...register('description')}
        />
        {errors.description && (
          <p className="text-sm text-destructive">{errors.description.message}</p>
        )}
      </div>

      <div className="grid gap-4 sm:grid-cols-2">
        <div className="space-y-1.5">
          <Label htmlFor="visibility">Visibility</Label>
          <Controller
            control={control}
            name="visibility"
            render={({ field }) => (
              <Select value={field.value} onValueChange={field.onChange}>
                <SelectTrigger id="visibility">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="private">Private</SelectItem>
                  <SelectItem value="unlisted">Unlisted</SelectItem>
                  <SelectItem value="public">Public</SelectItem>
                </SelectContent>
              </Select>
            )}
          />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="tags">Tags</Label>
          <Input id="tags" placeholder="networks, exam-prep" {...register('tags')} />
          <p className="text-xs text-muted-foreground">Comma separated.</p>
        </div>
      </div>

      <div className="flex justify-end gap-2 pt-2">
        {onCancel && (
          <Button type="button" variant="ghost" onClick={onCancel}>
            Cancel
          </Button>
        )}
        <Button type="submit" disabled={submitting}>
          {submitting && <Loader2 className="h-4 w-4 animate-spin" />}
          {submitLabel}
        </Button>
      </div>
    </form>
  );
}
