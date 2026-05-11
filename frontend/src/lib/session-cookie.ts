// Server-only helpers for the refresh-token cookie used by the auth BFF
// route handlers. The refresh token is httpOnly so it never reaches JS.

import type { NextRequest } from 'next/server';

export const REFRESH_COOKIE_NAME = 'lq_refresh';
const REFRESH_MAX_AGE_S = 60 * 60 * 24 * 7; // mirrors JWT_REFRESH_TTL_DAYS=7

function isHttps(req: NextRequest): boolean {
  const forwarded = req.headers.get('x-forwarded-proto');
  if (forwarded) return forwarded.split(',')[0].trim() === 'https';
  return req.nextUrl.protocol === 'https:';
}

export interface RefreshCookieOptions {
  httpOnly: true;
  sameSite: 'lax';
  path: string;
  secure: boolean;
  maxAge: number;
}

export function refreshCookieOptions(req: NextRequest): RefreshCookieOptions {
  return {
    httpOnly: true,
    sameSite: 'lax',
    path: '/session',
    secure: isHttps(req),
    maxAge: REFRESH_MAX_AGE_S,
  };
}

export function clearRefreshCookieOptions(req: NextRequest): RefreshCookieOptions {
  return { ...refreshCookieOptions(req), maxAge: 0 };
}
