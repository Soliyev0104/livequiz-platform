import { NextResponse, type NextRequest } from 'next/server';

import { INTERNAL_API_BASE } from '@/lib/env';
import {
  clearRefreshCookieOptions,
  REFRESH_COOKIE_NAME,
  refreshCookieOptions,
} from '@/lib/session-cookie';

export const dynamic = 'force-dynamic';

export async function POST(req: NextRequest): Promise<NextResponse> {
  const refreshToken = req.cookies.get(REFRESH_COOKIE_NAME)?.value;
  if (!refreshToken) {
    return NextResponse.json(
      { error: { code: 'AUTH_REQUIRED', message: 'No active session' } },
      { status: 401 },
    );
  }

  let upstream: Response;
  try {
    upstream = await fetch(`${INTERNAL_API_BASE}/auth/refresh`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh_token: refreshToken }),
      cache: 'no-store',
    });
  } catch {
    return NextResponse.json(
      { error: { code: 'UPSTREAM_UNAVAILABLE', message: 'Authentication service unavailable' } },
      { status: 502 },
    );
  }

  const data = (await upstream.json().catch(() => ({}))) as Record<string, unknown>;
  if (!upstream.ok) {
    const res = NextResponse.json(data, { status: upstream.status });
    res.cookies.set(REFRESH_COOKIE_NAME, '', clearRefreshCookieOptions(req));
    return res;
  }

  const res = NextResponse.json({
    access_token: data.access_token,
    expires_in: data.expires_in,
  });
  if (typeof data.refresh_token === 'string') {
    res.cookies.set(REFRESH_COOKIE_NAME, data.refresh_token, refreshCookieOptions(req));
  }
  return res;
}
