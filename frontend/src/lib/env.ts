// Runtime/build-time configuration. `NEXT_PUBLIC_*` are inlined at build
// time by Next.js; the defaults below mirror the values nginx expects so a
// plain `next build` (without Docker) also works against a local stack.

export const API_BASE: string = process.env.NEXT_PUBLIC_API_BASE ?? '/api/v1';
export const WS_BASE: string = process.env.NEXT_PUBLIC_WS_BASE ?? '/ws';

// Server-only: used by the auth BFF route handlers to reach the API.
export const INTERNAL_API_BASE: string =
  process.env.INTERNAL_API_BASE ?? 'http://localhost/api/v1';

// Show the seeded demo credentials card on the auth screens. Enabled by
// default for this project (it ships with a seeded demo database); set
// NEXT_PUBLIC_DEMO_MODE=0 to hide it.
export const DEMO_MODE: boolean = process.env.NEXT_PUBLIC_DEMO_MODE !== '0';

export const DEMO_CREDENTIALS = [
  { label: 'Host', email: 'host@livequiz.local', password: 'host' },
  { label: 'Moderator / Admin', email: 'admin@livequiz.local', password: 'admin' },
  { label: 'Player', email: 'player1@livequiz.local', password: 'player' },
] as const;
