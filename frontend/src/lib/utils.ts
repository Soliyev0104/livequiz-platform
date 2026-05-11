import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';

export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}

export function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max);
}

export function formatPercent(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—';
  return `${value.toFixed(digits)}%`;
}

export function formatMs(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—';
  if (value < 1000) return `${Math.round(value)} ms`;
  return `${(value / 1000).toFixed(value < 10_000 ? 2 : 1)} s`;
}

export function formatRelativeTime(iso: string | null | undefined): string {
  if (!iso) return '';
  const then = Date.parse(iso);
  if (Number.isNaN(then)) return '';
  const diffMs = Date.now() - then;
  const abs = Math.abs(diffMs);
  const minute = 60_000;
  const hour = 60 * minute;
  const day = 24 * hour;
  if (abs < minute) return 'just now';
  if (abs < hour) return `${Math.round(abs / minute)}m ago`;
  if (abs < day) return `${Math.round(abs / hour)}h ago`;
  if (abs < 7 * day) return `${Math.round(abs / day)}d ago`;
  return new Date(then).toLocaleDateString();
}

export function newRequestId(): string {
  // Browsers (and Node 19+) provide crypto.randomUUID.
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) {
    return crypto.randomUUID();
  }
  return `req-${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
}

export function ordinal(n: number): string {
  const s = ['th', 'st', 'nd', 'rd'];
  const v = n % 100;
  return n + (s[(v - 20) % 10] ?? s[v] ?? s[0]);
}
