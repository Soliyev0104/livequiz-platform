import { NextResponse, type NextRequest } from 'next/server';

import { INTERNAL_API_BASE } from '@/lib/env';
import { clearRefreshCookieOptions, REFRESH_COOKIE_NAME } from '@/lib/session-cookie';

export const dynamic = 'force-dynamic';

export async function POST(req: NextRequest): Promise<NextResponse> {
  const refreshToken = req.cookies.get(REFRESH_COOKIE_NAME)?.value;
  const authorization = req.headers.get('authorization');

  if (refreshToken && authorization) {
    try {
      await fetch(`${INTERNAL_API_BASE}/auth/logout`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: authorization },
        body: JSON.stringify({ refresh_token: refreshToken }),
        cache: 'no-store',
      });
    } catch {
      // best-effort — the cookie is cleared regardless
    }
  }

  const res = new NextResponse(null, { status: 204 });
  res.cookies.set(REFRESH_COOKIE_NAME, '', clearRefreshCookieOptions(req));
  return res;
}
