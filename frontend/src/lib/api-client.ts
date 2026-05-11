// fetch-based REST client for the LiveQuiz API.
//
//  * Auth interceptor: attaches `Authorization: Bearer <access>` from the
//    in-memory auth store (registered via `configureApiAuth`). On 401 it
//    asks the store to refresh (single-flight) and retries once.
//  * Mutating gameplay calls send an `X-Request-ID` (client-generated UUID)
//    for idempotency.
//  * Participant-token calls (answer submit, leaderboard, participant
//    analytics) pass the token explicitly instead of using the store.
//  * Errors are parsed from the `{ error: { code, message, details }, request_id }`
//    envelope into a thrown `ApiError`.

import { API_BASE } from './env';
import { newRequestId } from './utils';
import type {
  AnalyticsResponse,
  AnswerSubmitRequest,
  AnswerSubmitResponse,
  ApiErrorBody,
  DecisionRequest,
  DecisionResponse,
  LeaderboardResponse,
  MatchControlResponse,
  MatchStartedResponse,
  QuestionCreate,
  QuestionDetail,
  QuestionUpdate,
  QuizSetCreate,
  QuizSetDetail,
  QuizSetListResponse,
  QuizSetSummary,
  QuizSetUpdate,
  ReportCreate,
  ReportQueueResponse,
  ReportResponse,
  ReportStatus,
  RoomCreate,
  RoomCreateResponse,
  RoomJoinRequest,
  RoomJoinResponse,
  RoomSnapshotResponse,
  User,
} from './types';

export class ApiError extends Error {
  readonly code: string;
  readonly status: number;
  readonly details?: Record<string, unknown>;
  readonly requestId?: string;

  constructor(args: {
    code: string;
    message: string;
    status: number;
    details?: Record<string, unknown>;
    requestId?: string;
  }) {
    super(args.message);
    this.name = 'ApiError';
    this.code = args.code;
    this.status = args.status;
    this.details = args.details;
    this.requestId = args.requestId;
  }
}

// --- auth bridge (set by the Zustand auth store to avoid a circular import) -

interface ApiAuthBridge {
  getAccessToken: () => string | null;
  refreshAccessToken: () => Promise<boolean>;
}

let authBridge: ApiAuthBridge | null = null;

export function configureApiAuth(bridge: ApiAuthBridge): void {
  authBridge = bridge;
}

// --- request core ----------------------------------------------------------

type AuthMode = 'access' | 'participant' | 'none';

interface RequestOptions {
  method?: 'GET' | 'POST' | 'PATCH' | 'PUT' | 'DELETE';
  body?: unknown;
  auth?: AuthMode;
  participantToken?: string;
  requestId?: string;
  query?: Record<string, string | number | boolean | null | undefined>;
  signal?: AbortSignal;
}

function buildUrl(path: string, query?: RequestOptions['query']): string {
  const base = `${API_BASE}${path}`;
  if (!query) return base;
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value === null || value === undefined || value === '') continue;
    params.set(key, String(value));
  }
  const qs = params.toString();
  return qs ? `${base}?${qs}` : base;
}

async function parseError(res: Response): Promise<ApiError> {
  let body: ApiErrorBody | undefined;
  try {
    body = (await res.json()) as ApiErrorBody;
  } catch {
    body = undefined;
  }
  const err = body?.error;
  return new ApiError({
    code: err?.code ?? `HTTP_${res.status}`,
    message: err?.message ?? res.statusText ?? 'Request failed',
    status: res.status,
    details: err?.details,
    requestId: body?.request_id,
  });
}

async function rawRequest<T>(path: string, opts: RequestOptions, isRetry: boolean): Promise<T> {
  const method = opts.method ?? 'GET';
  const headers: Record<string, string> = { Accept: 'application/json' };
  const auth: AuthMode = opts.auth ?? 'access';

  if (auth === 'access') {
    const token = authBridge?.getAccessToken() ?? null;
    if (token) headers.Authorization = `Bearer ${token}`;
  } else if (auth === 'participant' && opts.participantToken) {
    headers.Authorization = `Bearer ${opts.participantToken}`;
  }

  if (opts.requestId) headers['X-Request-ID'] = opts.requestId;

  let bodyInit: BodyInit | undefined;
  if (opts.body !== undefined && opts.body !== null) {
    headers['Content-Type'] = 'application/json';
    bodyInit = JSON.stringify(opts.body);
  }

  const res = await fetch(buildUrl(path, opts.query), {
    method,
    headers,
    body: bodyInit,
    signal: opts.signal,
    credentials: 'same-origin',
  });

  if (res.status === 401 && auth === 'access' && !isRetry && authBridge) {
    const refreshed = await authBridge.refreshAccessToken();
    if (refreshed) return rawRequest<T>(path, opts, true);
  }

  if (!res.ok) throw await parseError(res);

  if (res.status === 204) return undefined as T;
  const text = await res.text();
  if (!text) return undefined as T;
  return JSON.parse(text) as T;
}

export function apiRequest<T>(path: string, opts: RequestOptions = {}): Promise<T> {
  return rawRequest<T>(path, opts, false);
}

// --- typed endpoint groups -------------------------------------------------

export const api = {
  auth: {
    register(body: { email: string; password: string; display_name: string }) {
      return apiRequest<User>('/auth/register', { method: 'POST', body, auth: 'none' });
    },
  },

  users: {
    me() {
      return apiRequest<User>('/me', { auth: 'access' });
    },
  },

  quizSets: {
    list(
      params: {
        q?: string;
        owner_id?: string | number;
        tag?: string;
        limit?: number;
        offset?: number;
      } = {},
    ) {
      return apiRequest<QuizSetListResponse>('/quiz-sets', { auth: 'none', query: params });
    },
    listMine(ownerId: string | number, limit = 100) {
      return apiRequest<QuizSetListResponse>('/quiz-sets', {
        auth: 'access',
        query: { owner_id: ownerId, limit },
      });
    },
    get(id: string | number) {
      return apiRequest<QuizSetDetail>(`/quiz-sets/${id}`, { auth: 'access' });
    },
    create(body: QuizSetCreate) {
      return apiRequest<QuizSetSummary>('/quiz-sets', { method: 'POST', body, auth: 'access' });
    },
    update(id: string | number, body: QuizSetUpdate) {
      return apiRequest<QuizSetSummary>(`/quiz-sets/${id}`, {
        method: 'PATCH',
        body,
        auth: 'access',
      });
    },
    publish(id: string | number) {
      return apiRequest<QuizSetSummary>(`/quiz-sets/${id}/publish`, {
        method: 'POST',
        auth: 'access',
      });
    },
    addQuestion(id: string | number, body: QuestionCreate) {
      return apiRequest<QuestionDetail>(`/quiz-sets/${id}/questions`, {
        method: 'POST',
        body,
        auth: 'access',
      });
    },
  },

  questions: {
    update(id: string | number, body: QuestionUpdate) {
      return apiRequest<QuestionDetail>(`/questions/${id}`, {
        method: 'PATCH',
        body,
        auth: 'access',
      });
    },
    remove(id: string | number) {
      return apiRequest<void>(`/questions/${id}`, { method: 'DELETE', auth: 'access' });
    },
  },

  rooms: {
    create(body: RoomCreate) {
      return apiRequest<RoomCreateResponse>('/rooms', { method: 'POST', body, auth: 'access' });
    },
    get(code: string) {
      return apiRequest<RoomSnapshotResponse>(`/rooms/${code}`, { auth: 'none' });
    },
    join(code: string, body: RoomJoinRequest, accessToken?: string) {
      // Authenticated users may pass their access token; guests omit it.
      return apiRequest<RoomJoinResponse>(`/rooms/${code}/join`, {
        method: 'POST',
        body,
        auth: accessToken ? 'participant' : 'none',
        participantToken: accessToken,
      });
    },
    start(code: string) {
      return apiRequest<MatchStartedResponse>(`/rooms/${code}/start`, {
        method: 'POST',
        auth: 'access',
      });
    },
    pause(code: string) {
      return apiRequest<MatchControlResponse>(`/rooms/${code}/pause`, {
        method: 'POST',
        auth: 'access',
      });
    },
    resume(code: string) {
      return apiRequest<MatchControlResponse>(`/rooms/${code}/resume`, {
        method: 'POST',
        auth: 'access',
      });
    },
    end(code: string) {
      return apiRequest<MatchControlResponse>(`/rooms/${code}/end`, {
        method: 'POST',
        auth: 'access',
      });
    },
  },

  matches: {
    submitAnswer(
      matchId: string | number,
      body: AnswerSubmitRequest,
      participantToken: string,
      requestId?: string,
    ) {
      return apiRequest<AnswerSubmitResponse>(`/matches/${matchId}/answers`, {
        method: 'POST',
        body,
        auth: 'participant',
        participantToken,
        requestId: requestId ?? newRequestId(),
      });
    },
    leaderboard(matchId: string | number, participantToken: string, limit = 10) {
      return apiRequest<LeaderboardResponse>(`/matches/${matchId}/leaderboard`, {
        auth: 'participant',
        participantToken,
        query: { limit },
      });
    },
    analytics(matchId: string | number, opts?: { participantToken?: string }) {
      if (opts?.participantToken) {
        return apiRequest<AnalyticsResponse>(`/matches/${matchId}/analytics`, {
          auth: 'participant',
          participantToken: opts.participantToken,
        });
      }
      return apiRequest<AnalyticsResponse>(`/matches/${matchId}/analytics`, { auth: 'access' });
    },
  },

  reports: {
    create(body: ReportCreate, accessToken?: string) {
      return apiRequest<ReportResponse>('/reports', {
        method: 'POST',
        body,
        auth: accessToken ? 'participant' : 'none',
        participantToken: accessToken,
      });
    },
  },

  moderation: {
    listReports(params: { status?: ReportStatus; limit?: number; offset?: number } = {}) {
      return apiRequest<ReportQueueResponse>('/moderation/reports', { auth: 'access', query: params });
    },
    decide(reportId: string | number, body: DecisionRequest) {
      return apiRequest<DecisionResponse>(`/moderation/reports/${reportId}/decision`, {
        method: 'POST',
        body,
        auth: 'access',
      });
    },
  },
};
