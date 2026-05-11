'use client';

// Result of `POST /rooms/{code}/join` — stashed in sessionStorage so the
// `/play/[code]` page can connect to the room WebSocket and submit answers.

export interface PlayerRoomSession {
  code: string;
  roomId: string;
  participantId: string;
  nickname: string;
  participantToken: string;
  wsUrl: string;
}

const key = (code: string): string => `lq:player-room:${code.toUpperCase()}`;

export function savePlayerRoomSession(session: PlayerRoomSession): void {
  if (typeof window === 'undefined') return;
  try {
    window.sessionStorage.setItem(key(session.code), JSON.stringify(session));
  } catch {
    // ignore
  }
}

export function loadPlayerRoomSession(code: string): PlayerRoomSession | null {
  if (typeof window === 'undefined') return null;
  try {
    const raw = window.sessionStorage.getItem(key(code));
    return raw ? (JSON.parse(raw) as PlayerRoomSession) : null;
  } catch {
    return null;
  }
}

export function clearPlayerRoomSession(code: string): void {
  if (typeof window === 'undefined') return;
  try {
    window.sessionStorage.removeItem(key(code));
  } catch {
    // ignore
  }
}
