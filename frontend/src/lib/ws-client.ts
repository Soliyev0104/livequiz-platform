'use client';

// Reconnecting WebSocket client for the live-room protocol.
//
//  * connect(): opens the socket; on an unexpected close it retries with
//    exponential backoff (500/1000/2000/5000 ms, capped at 5000) and then
//    fires `onReconnect()` so the page can re-fetch the REST snapshot. The
//    server also re-pushes `room.snapshot` on every connect.
//  * send(type, payload): wraps the message in the protocol envelope with a
//    fresh `message_id` (UUID) and `sent_at`. Returns the `message_id` so the
//    caller can reuse it as an idempotency key (answer submissions).
//  * Heartbeat every 20s (server disconnects after 60s of silence).
//  * Outbound messages are buffered while disconnected (max 50, drop oldest)
//    and flushed on open.

import { WS_BASE } from './env';
import type { ClientMessageType, ServerMessage } from './types';
import { newRequestId } from './utils';

export interface LiveSocketCallbacks {
  onOpen?: (isReconnect: boolean) => void;
  onMessage?: (msg: ServerMessage) => void;
  onClose?: (info: { code: number; reason: string; willReconnect: boolean }) => void;
  onReconnect?: () => void;
  onError?: (err: unknown) => void;
}

const BACKOFF_MS = [500, 1000, 2000, 5000];
const HEARTBEAT_INTERVAL_MS = 20_000;
const MAX_BUFFER = 50;
// Close codes the backend uses for auth/heartbeat failures — do not retry on
// auth failures (a stale token will keep failing).
const NO_RETRY_CODES = new Set([4401, 4400, 1008]);

/** Build an absolute ws(s):// URL pointed at the current origin.
 *
 * Accepts the backend-provided `ws_url`/`host_ws_url` (which may be a
 * relative path like `/ws/rooms/CODE?token=...` or an absolute URL whose
 * host we ignore — the browser must reach the room through the same nginx),
 * or a `{ code, token }` pair. */
export function resolveWsUrl(input: { relativeUrl?: string; code?: string; token?: string }): string {
  if (typeof window === 'undefined') return input.relativeUrl ?? '';
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const host = window.location.host;

  let pathAndQuery: string;
  if (input.relativeUrl) {
    const raw = input.relativeUrl;
    if (/^wss?:\/\//i.test(raw) || /^https?:\/\//i.test(raw)) {
      try {
        const u = new URL(raw);
        pathAndQuery = `${u.pathname}${u.search}`;
      } catch {
        pathAndQuery = raw;
      }
    } else {
      pathAndQuery = raw.startsWith('/') ? raw : `/${raw}`;
    }
  } else {
    const code = encodeURIComponent(input.code ?? '');
    const token = encodeURIComponent(input.token ?? '');
    pathAndQuery = `${WS_BASE}/rooms/${code}?token=${token}`;
  }
  return `${proto}//${host}${pathAndQuery}`;
}

interface QueuedMessage {
  type: ClientMessageType;
  payload: unknown;
}

export class LiveSocket {
  private ws: WebSocket | null = null;
  private readonly url: string;
  private readonly cb: LiveSocketCallbacks;
  private heartbeatTimer: ReturnType<typeof setInterval> | null = null;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private attempt = 0;
  private closedByUs = false;
  private hasConnectedOnce = false;
  private lastSeenEventId: string | null = null;
  private outbuffer: QueuedMessage[] = [];

  constructor(url: string, callbacks: LiveSocketCallbacks) {
    this.url = url;
    this.cb = callbacks;
  }

  connect(): void {
    this.closedByUs = false;
    this.open();
  }

  private open(): void {
    if (typeof window === 'undefined') return;
    try {
      this.ws = new WebSocket(this.url);
    } catch (err) {
      this.cb.onError?.(err);
      this.scheduleReconnect();
      return;
    }

    this.ws.onopen = () => {
      const isReconnect = this.hasConnectedOnce;
      this.hasConnectedOnce = true;
      this.attempt = 0;
      this.startHeartbeat();
      this.flushBuffer();
      this.cb.onOpen?.(isReconnect);
      if (isReconnect) this.cb.onReconnect?.();
    };

    this.ws.onmessage = (event: MessageEvent) => {
      let msg: ServerMessage;
      try {
        msg = JSON.parse(typeof event.data === 'string' ? event.data : '') as ServerMessage;
      } catch (err) {
        this.cb.onError?.(err);
        return;
      }
      if (msg && typeof msg.message_id === 'string') this.lastSeenEventId = msg.message_id;
      this.cb.onMessage?.(msg);
    };

    this.ws.onerror = (event) => {
      this.cb.onError?.(event);
    };

    this.ws.onclose = (event: CloseEvent) => {
      this.stopHeartbeat();
      const willReconnect = !this.closedByUs && !NO_RETRY_CODES.has(event.code);
      this.cb.onClose?.({ code: event.code, reason: event.reason, willReconnect });
      if (willReconnect) this.scheduleReconnect();
    };
  }

  private scheduleReconnect(): void {
    if (this.reconnectTimer) return;
    const delay = BACKOFF_MS[Math.min(this.attempt, BACKOFF_MS.length - 1)];
    this.attempt += 1;
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      if (this.closedByUs) return;
      this.open();
    }, delay);
  }

  private startHeartbeat(): void {
    this.stopHeartbeat();
    this.heartbeatTimer = setInterval(() => {
      this.rawSend({ type: 'room.heartbeat', payload: { last_seen_event_id: this.lastSeenEventId } });
    }, HEARTBEAT_INTERVAL_MS);
  }

  private stopHeartbeat(): void {
    if (this.heartbeatTimer) {
      clearInterval(this.heartbeatTimer);
      this.heartbeatTimer = null;
    }
  }

  private flushBuffer(): void {
    if (!this.outbuffer.length) return;
    const pending = this.outbuffer.splice(0, this.outbuffer.length);
    for (const m of pending) this.send(m.type, m.payload);
  }

  /** Send a client message. Returns the generated `message_id`. */
  send(type: ClientMessageType, payload: unknown): string {
    const messageId = newRequestId();
    const ok = this.rawSend({ type, payload, message_id: messageId, sent_at: new Date().toISOString() });
    if (!ok) {
      this.outbuffer.push({ type, payload });
      if (this.outbuffer.length > MAX_BUFFER) this.outbuffer.shift();
    }
    return messageId;
  }

  private rawSend(envelope: Record<string, unknown>): boolean {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return false;
    try {
      this.ws.send(JSON.stringify(envelope));
      return true;
    } catch {
      return false;
    }
  }

  get isOpen(): boolean {
    return this.ws?.readyState === WebSocket.OPEN;
  }

  close(): void {
    this.closedByUs = true;
    this.stopHeartbeat();
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    if (this.ws) {
      this.ws.onopen = null;
      this.ws.onmessage = null;
      this.ws.onerror = null;
      this.ws.onclose = null;
      try {
        this.ws.close(1000, 'client closed');
      } catch {
        // ignore
      }
      this.ws = null;
    }
  }
}
