'use client';

// The host's WebSocket token is only returned by `POST /rooms` (there is no
// endpoint to re-mint it). We stash it in sessionStorage so the host control
// page can connect; if it is missing the page sends the host back to the
// dashboard to create a fresh room.

export interface HostRoomSession {
  code: string;
  roomId: string;
  hostWsUrl: string;
  quizSetId: string;
  quizTitle: string;
}

const key = (code: string): string => `lq:host-room:${code.toUpperCase()}`;

export function saveHostRoomSession(session: HostRoomSession): void {
  if (typeof window === 'undefined') return;
  try {
    window.sessionStorage.setItem(key(session.code), JSON.stringify(session));
  } catch {
    // ignore
  }
}

export function loadHostRoomSession(code: string): HostRoomSession | null {
  if (typeof window === 'undefined') return null;
  try {
    const raw = window.sessionStorage.getItem(key(code));
    return raw ? (JSON.parse(raw) as HostRoomSession) : null;
  } catch {
    return null;
  }
}

export function clearHostRoomSession(code: string): void {
  if (typeof window === 'undefined') return;
  try {
    window.sessionStorage.removeItem(key(code));
  } catch {
    // ignore
  }
}
