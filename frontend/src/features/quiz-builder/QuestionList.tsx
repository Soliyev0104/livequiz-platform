'use client';

import {
  DndContext,
  type DragEndEvent,
  KeyboardSensor,
  PointerSensor,
  closestCenter,
  useSensor,
  useSensors,
} from '@dnd-kit/core';
import {
  SortableContext,
  arrayMove,
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy,
} from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';
import { AlertTriangle, GripVertical, Plus } from 'lucide-react';
import * as React from 'react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';
import type { QuestionDetail } from '@/lib/types';

const TYPE_LABEL: Record<QuestionDetail['type'], string> = {
  single_choice: 'Single',
  multiple_choice: 'Multiple',
  true_false: 'True/False',
};

function SortableQuestion({
  question,
  index,
  active,
  invalid,
  onSelect,
}: {
  question: QuestionDetail;
  index: number;
  active: boolean;
  invalid: boolean;
  onSelect: () => void;
}): React.JSX.Element {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id: question.id,
  });
  return (
    <li
      ref={setNodeRef}
      style={{ transform: CSS.Transform.toString(transform), transition }}
      className={cn('list-none', isDragging && 'opacity-60')}
    >
      <div
        className={cn(
          'flex items-center gap-2 rounded-lg border px-2 py-2 text-sm transition-colors',
          active ? 'border-primary bg-accent/50' : 'border-border/60 hover:bg-accent/30',
        )}
      >
        <button
          type="button"
          className="cursor-grab rounded p-1 text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring active:cursor-grabbing"
          aria-label={`Reorder question ${index + 1}`}
          {...attributes}
          {...listeners}
        >
          <GripVertical className="h-4 w-4" />
        </button>
        <button
          type="button"
          onClick={onSelect}
          className="flex min-w-0 flex-1 items-center gap-2 text-left focus-visible:outline-none"
        >
          <span className="grid h-6 w-6 shrink-0 place-items-center rounded-full bg-muted text-xs font-medium">
            {index + 1}
          </span>
          <span className="min-w-0 flex-1 truncate">{question.body || 'Untitled question'}</span>
          {invalid && <AlertTriangle className="h-3.5 w-3.5 shrink-0 text-destructive" />}
          <Badge variant="muted" className="shrink-0">
            {TYPE_LABEL[question.type]}
          </Badge>
        </button>
      </div>
    </li>
  );
}

interface QuestionListProps {
  questions: QuestionDetail[];
  selectedId: string | null;
  invalidIds: Set<string>;
  onSelect: (id: string) => void;
  onReorder: (movedQuestionId: string, newPosition: number, orderedIds: string[]) => void;
  onAdd: () => void;
  adding: boolean;
}

export function QuestionList({
  questions,
  selectedId,
  invalidIds,
  onSelect,
  onReorder,
  onAdd,
  adding,
}: QuestionListProps): React.JSX.Element {
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 4 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  );

  const ids = questions.map((q) => q.id);

  function handleDragEnd(event: DragEndEvent): void {
    const { active, over } = event;
    if (!over || active.id === over.id) return;
    const oldIndex = ids.indexOf(String(active.id));
    const newIndex = ids.indexOf(String(over.id));
    if (oldIndex < 0 || newIndex < 0) return;
    const ordered = arrayMove(ids, oldIndex, newIndex);
    onReorder(String(active.id), newIndex + 1, ordered);
  }

  return (
    <div className="flex h-full flex-col">
      <div className="mb-2 flex items-center justify-between">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
          Questions ({questions.length})
        </h2>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto">
        {questions.length === 0 ? (
          <p className="rounded-lg border border-dashed border-border/60 p-4 text-sm text-muted-foreground">
            No questions yet. Add your first question below.
          </p>
        ) : (
          <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={handleDragEnd}>
            <SortableContext items={ids} strategy={verticalListSortingStrategy}>
              <ul className="space-y-1.5">
                {questions.map((q, i) => (
                  <SortableQuestion
                    key={q.id}
                    question={q}
                    index={i}
                    active={q.id === selectedId}
                    invalid={invalidIds.has(q.id)}
                    onSelect={() => onSelect(q.id)}
                  />
                ))}
              </ul>
            </SortableContext>
          </DndContext>
        )}
      </div>
      <Button
        variant="outline"
        className="mt-3 w-full"
        onClick={onAdd}
        disabled={adding}
      >
        <Plus className="h-4 w-4" /> Add question
      </Button>
    </div>
  );
}
