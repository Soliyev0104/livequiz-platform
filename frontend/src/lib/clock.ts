// Local countdowns must be anchored to the server clock, not the browser
// wall clock (which may be skewed). We compute the offset once from a
// `server_now` field and use it for the rest of the match.

export function computeSkewMs(serverNowIso: string): number {
  const serverMs = Date.parse(serverNowIso);
  if (Number.isNaN(serverMs)) return 0;
  return serverMs - Date.now();
}

export function serverNowMs(skewMs: number): number {
  return Date.now() + skewMs;
}

/** Milliseconds remaining until `deadlineIso`, never negative. */
export function remainingMs(deadlineIso: string, skewMs: number): number {
  const deadline = Date.parse(deadlineIso);
  if (Number.isNaN(deadline)) return 0;
  return Math.max(0, deadline - serverNowMs(skewMs));
}

/** Total duration of the window [startedIso, deadlineIso] in milliseconds. */
export function windowMs(startedIso: string, deadlineIso: string): number {
  const start = Date.parse(startedIso);
  const end = Date.parse(deadlineIso);
  if (Number.isNaN(start) || Number.isNaN(end) || end <= start) return 0;
  return end - start;
}
