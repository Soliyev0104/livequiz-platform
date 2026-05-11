import { NextResponse, type NextRequest } from 'next/server';

import { INTERNAL_API_BASE } from '@/lib/env';
import { REFRESH_COOKIE_NAME, refreshCookieOptions } from '@/lib/session-cookie';

export const dynamic = 'force-dynamic';

export async function POST(req: NextRequest): Promise<NextResponse> {
  let body: { email?: string; password?: string };
  try {
    body = (await req.json()) as { email?: string; password?: string };
  } catch {
    return NextResponse.json(
      { error: { code: 'VALIDATION_ERROR', message: 'Invalid request body' } },
      { status: 400 },
    );
  }

  let upstream: Response;
  try {
    upstream = await fetch(`${INTERNAL_API_BASE}/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email: body.email, password: body.password }),
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
    return NextResponse.json(data, { status: upstream.status });
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
