'use client';

// The API does not expose a "list my rooms" endpoint, so the dashboard's
// "recent rooms" list is reconstructed from localStorage. Entries are written
// whenever a host creates a room.

import * as React from 'react';

const KEY = 'lq:recent-rooms';
const MAX = 8;

export interface RecentRoom {
  code: string;
  quizTitle: string;
  createdAt: string;
}

function read(): RecentRoom[] {
  if (typeof window === 'undefined') return [];
  try {
    const raw = window.localStorage.getItem(KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as RecentRoom[];
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function write(rooms: RecentRoom[]): void {
  if (typeof window === 'undefined') return;
  try {
    window.localStorage.setItem(KEY, JSON.stringify(rooms.slice(0, MAX)));
    window.dispatchEvent(new Event('lq:recent-rooms-changed'));
  } catch {
    // storage unavailable — ignore
  }
}

export function rememberRoom(room: RecentRoom): void {
  const existing = read().filter((r) => r.code !== room.code);
  write([room, ...existing]);
}

export function useRecentRooms(): RecentRoom[] {
  const [rooms, setRooms] = React.useState<RecentRoom[]>([]);
  React.useEffect(() => {
    const sync = () => setRooms(read());
    sync();
    window.addEventListener('lq:recent-rooms-changed', sync);
    window.addEventListener('storage', sync);
    return () => {
      window.removeEventListener('lq:recent-rooms-changed', sync);
      window.removeEventListener('storage', sync);
    };
  }, []);
  return rooms;
}
