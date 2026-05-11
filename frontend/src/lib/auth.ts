'use client';

// In-memory auth store. The access token lives only in JS memory; the
// refresh token never touches JS — it is held in an httpOnly cookie by the
// Next.js auth BFF route handlers (`/session/*`, served by the frontend, not
// the API — nginx routes everything under `/api/` to the backend). On startup
// we call `/session/refresh`, which mints a fresh access token from the cookie.

import { create } from 'zustand';

import { api, ApiError, configureApiAuth } from './api-client';
import type { ApiErrorBody, User } from './types';

export type AuthStatus = 'idle' | 'loading' | 'authed' | 'anon';

interface AuthState {
  accessToken: string | null;
  user: User | null;
  status: AuthStatus;
  hydrate: () => Promise<void>;
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, password: string, displayName: string) => Promise<void>;
  refreshAccess: () => Promise<boolean>;
  fetchMe: () => Promise<void>;
  logout: () => Promise<void>;
}

interface SessionResponse {
  access_token: string;
  expires_in: number;
}

async function bffPost(path: string, body?: unknown, accessToken?: string): Promise<Response> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' };
  if (accessToken) headers.Authorization = `Bearer ${accessToken}`;
  return fetch(path, {
    method: 'POST',
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
    credentials: 'same-origin',
  });
}

async function readError(res: Response, fallback: string): Promise<ApiError> {
  let parsed: ApiErrorBody | undefined;
  try {
    parsed = (await res.json()) as ApiErrorBody;
  } catch {
    parsed = undefined;
  }
  return new ApiError({
    code: parsed?.error?.code ?? `HTTP_${res.status}`,
    message: parsed?.error?.message ?? fallback,
    status: res.status,
    details: parsed?.error?.details,
    requestId: parsed?.request_id,
  });
}

// Single-flight refresh so concurrent 401s do not stampede the endpoint.
let refreshInFlight: Promise<boolean> | null = null;

export const useAuthStore = create<AuthState>((set, get) => ({
  accessToken: null,
  user: null,
  status: 'idle',

  async hydrate() {
    if (get().status === 'authed') return;
    set({ status: 'loading' });
    const ok = await get().refreshAccess();
    if (ok) {
      try {
        await get().fetchMe();
        return;
      } catch {
        set({ accessToken: null, user: null, status: 'anon' });
        return;
      }
    }
    set({ status: 'anon' });
  },

  async login(email, password) {
    const res = await bffPost('/session/login', { email, password });
    if (!res.ok) throw await readError(res, 'Login failed');
    const data = (await res.json()) as SessionResponse;
    set({ accessToken: data.access_token });
    await get().fetchMe();
  },

  async register(email, password, displayName) {
    await api.auth.register({ email, password, display_name: displayName });
    await get().login(email, password);
  },

  async refreshAccess() {
    if (refreshInFlight) return refreshInFlight;
    refreshInFlight = (async () => {
      try {
        const res = await bffPost('/session/refresh');
        if (!res.ok) {
          set({ accessToken: null, user: null, status: 'anon' });
          return false;
        }
        const data = (await res.json()) as SessionResponse;
        set({ accessToken: data.access_token });
        return true;
      } catch {
        set({ accessToken: null, user: null, status: 'anon' });
        return false;
      } finally {
        refreshInFlight = null;
      }
    })();
    return refreshInFlight;
  },

  async fetchMe() {
    const user = await api.users.me();
    set({ user, status: 'authed' });
  },

  async logout() {
    const token = get().accessToken ?? undefined;
    try {
      await bffPost('/session/logout', undefined, token);
    } catch {
      // best-effort
    }
    set({ accessToken: null, user: null, status: 'anon' });
  },
}));

// Bridge the api-client to this store (avoids a circular import).
configureApiAuth({
  getAccessToken: () => useAuthStore.getState().accessToken,
  refreshAccessToken: () => useAuthStore.getState().refreshAccess(),
});

export function hasRole(user: User | null, ...roles: User['role'][]): boolean {
  return !!user && roles.includes(user.role);
}
