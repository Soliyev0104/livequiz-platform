'use client';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api } from '@/lib/api-client';
import type {
  QuestionCreate,
  QuestionUpdate,
  QuizSetCreate,
  QuizSetUpdate,
} from '@/lib/types';

export function useQuizSet(id: string) {
  return useQuery({
    queryKey: ['quiz-set', id],
    queryFn: () => api.quizSets.get(id),
    enabled: !!id,
    staleTime: 0,
  });
}

function useInvalidateQuiz(id?: string) {
  const qc = useQueryClient();
  return () => {
    void qc.invalidateQueries({ queryKey: ['quiz-sets'] });
    if (id) void qc.invalidateQueries({ queryKey: ['quiz-set', id] });
  };
}

export function useCreateQuizSet() {
  const invalidate = useInvalidateQuiz();
  return useMutation({
    mutationFn: (body: QuizSetCreate) => api.quizSets.create(body),
    onSuccess: invalidate,
  });
}

export function useUpdateQuizSet(id: string) {
  const invalidate = useInvalidateQuiz(id);
  return useMutation({
    mutationFn: (body: QuizSetUpdate) => api.quizSets.update(id, body),
    onSuccess: invalidate,
  });
}

export function usePublishQuizSet(id: string) {
  const invalidate = useInvalidateQuiz(id);
  return useMutation({
    mutationFn: () => api.quizSets.publish(id),
    onSuccess: invalidate,
  });
}

export function useAddQuestion(id: string) {
  const invalidate = useInvalidateQuiz(id);
  return useMutation({
    mutationFn: (body: QuestionCreate) => api.quizSets.addQuestion(id, body),
    onSuccess: invalidate,
  });
}

export function useUpdateQuestion(quizId: string) {
  const invalidate = useInvalidateQuiz(quizId);
  return useMutation({
    mutationFn: ({ questionId, body }: { questionId: string; body: QuestionUpdate }) =>
      api.questions.update(questionId, body),
    onSuccess: invalidate,
  });
}

export function useDeleteQuestion(quizId: string) {
  const invalidate = useInvalidateQuiz(quizId);
  return useMutation({
    mutationFn: (questionId: string) => api.questions.remove(questionId),
    onSuccess: invalidate,
  });
}
