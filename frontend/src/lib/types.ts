// Curated TypeScript types for the LiveQuiz API + WebSocket protocol.
//
// These are hand-authored to mirror the backend Pydantic schemas
// (`backend/app/schemas/*.py`) and the WebSocket envelope models
// (`backend/app/ws/messages.py`), per `docs/06_api_contracts.md` and
// `docs/07_websocket_protocol.md`. All Snowflake IDs are serialized by the
// backend as JSON strings, so they are typed as `string` here.
//
// (`openapi-typescript` could generate these instead; the generated file is
// intentionally omitted so the build does not depend on a running backend.
// If desired, regenerate with:
//   pnpm dlx openapi-typescript http://localhost/api/openapi.json -o src/lib/api-types.ts )

export type Role = 'player' | 'host' | 'moderator' | 'admin';
export type Visibility = 'private' | 'unlisted' | 'public';
export type QuestionType = 'single_choice' | 'multiple_choice' | 'true_false';
export type RoomStatus = 'lobby' | 'running' | 'paused' | 'completed' | 'cancelled';
export type MatchStatus = 'running' | 'paused' | 'completed' | 'cancelled';
export type ReportStatus = 'pending' | 'dismissed' | 'action_taken';
export type DecisionAction = 'dismiss' | 'hide' | 'mute' | 'ban';

// ---------------------------------------------------------------------------
// Auth / users
// ---------------------------------------------------------------------------

export interface User {
  id: string;
  email: string;
  display_name: string;
  role: Role;
}

export interface TokenPair {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
}

/** Shape returned by the Next.js auth BFF route handlers (no refresh token). */
export interface SessionTokens {
  access_token: string;
  expires_in: number;
}

// ---------------------------------------------------------------------------
// Quiz sets / questions
// ---------------------------------------------------------------------------

export interface QuizSetSummary {
  id: string;
  title: string;
  is_published: boolean;
  version: number;
  question_count: number;
}

export interface OptionDetail {
  id: string;
  position: number;
  body: string;
  is_correct: boolean;
}

export interface QuestionDetail {
  id: string;
  position: number;
  body: string;
  type: QuestionType;
  time_limit_seconds: number;
  points: number;
  explanation: string | null;
  options: OptionDetail[];
}

export interface QuizSetDetail {
  id: string;
  title: string;
  description: string | null;
  visibility: Visibility;
  is_published: boolean;
  version: number;
  owner_id: string;
  tags: string[];
  question_count: number;
  created_at: string;
  updated_at: string;
  // Only present when the requester owns the quiz set.
  questions: QuestionDetail[] | null;
}

export interface QuizSetListResponse {
  items: QuizSetSummary[];
  limit: number;
  offset: number;
}

export interface QuizSetCreate {
  title: string;
  description?: string | null;
  visibility?: Visibility;
  tags?: string[];
}

export interface QuizSetUpdate {
  title?: string;
  description?: string | null;
  visibility?: Visibility;
  tags?: string[] | null;
}

export interface OptionInput {
  position: number;
  body: string;
  is_correct: boolean;
}

export interface QuestionCreate {
  position?: number;
  body: string;
  type: QuestionType;
  time_limit_seconds?: number;
  points?: number;
  explanation?: string | null;
  options: OptionInput[];
}

export interface QuestionUpdate {
  position?: number;
  body?: string;
  type?: QuestionType;
  time_limit_seconds?: number;
  points?: number;
  explanation?: string | null;
  options?: OptionInput[] | null;
}

// ---------------------------------------------------------------------------
// Rooms / matches
// ---------------------------------------------------------------------------

export interface RoomCreate {
  quiz_set_id: string | number;
  max_players?: number;
  settings?: Record<string, unknown>;
}

export interface RoomCreateResponse {
  room_id: string;
  code: string;
  status: RoomStatus;
  host_ws_url: string;
}

export interface RoomSnapshotRoom {
  code: string;
  status: RoomStatus;
  player_count: number;
}

export interface RoomSnapshotParticipant {
  participant_id: string;
  nickname: string;
  online: boolean;
}

export interface LeaderboardEntry {
  rank: number;
  participant_id: string;
  nickname: string;
  score: number;
}

/** The `match` sub-object of a room snapshot. The backend keeps it loosely
 * typed; we model the fields we rely on and tolerate extras. */
export interface RoomSnapshotMatch {
  match_id: string;
  question_count?: number;
  status?: MatchStatus;
  // Present (cached in Redis) while a question is live, on reconnect.
  current_question?: QuestionStartedPayload | null;
  [key: string]: unknown;
}

export interface RoomSnapshotResponse {
  room: RoomSnapshotRoom;
  participants: RoomSnapshotParticipant[];
  match: RoomSnapshotMatch | null;
  leaderboard: LeaderboardEntry[];
}

export interface RoomJoinRequest {
  nickname: string;
  guest_id?: string;
}

export interface RoomJoinResponse {
  participant_id: string;
  room_id: string;
  code: string;
  nickname: string;
  participant_token: string;
  ws_url: string;
}

export interface MatchStartedResponse {
  match_id: string;
  room_code: string;
  question_count: number;
  status: MatchStatus;
}

export interface MatchControlResponse {
  match_id: string;
  status: MatchStatus;
}

export interface AnswerSubmitRequest {
  match_question_id: string | number;
  selected_option_ids: Array<string | number>;
  client_sent_at?: string;
}

export interface AnswerSubmitResponse {
  submission_id: string;
  accepted: boolean;
  is_correct: boolean;
  score_awarded: number;
  response_time_ms: number;
  leaderboard_rank: number | null;
}

export interface LeaderboardResponse {
  match_id: string;
  is_final: boolean;
  entries: LeaderboardEntry[];
}

// ---------------------------------------------------------------------------
// Analytics
// ---------------------------------------------------------------------------

export interface QuestionAccuracyRow {
  question_id: string;
  total_answers: number;
  correct_answers: number;
  accuracy_percent: number;
  avg_response_ms: number;
}

export interface ResponseTimeDistribution {
  p50_ms: number;
  p95_ms: number;
  p99_ms: number;
  avg_ms: number;
}

export interface FinalLeaderboardRow {
  rank: number;
  participant_id: string;
  nickname: string;
  total_score: number;
  correct_count: number;
  average_response_ms: number;
}

export interface AnalyticsResponse {
  match_id: string;
  question_accuracy?: QuestionAccuracyRow[];
  response_time_distribution?: ResponseTimeDistribution | null;
  most_missed_questions?: QuestionAccuracyRow[];
  total_answers: number;
  final_leaderboard: FinalLeaderboardRow[];
}

// ---------------------------------------------------------------------------
// Moderation
// ---------------------------------------------------------------------------

export interface ReportCreate {
  reason: string;
  details?: string | null;
  target_user_id?: string | number | null;
  target_quiz_set_id?: string | number | null;
  room_id?: string | number | null;
}

export interface ReportResponse {
  id: string;
  reporter_user_id: string | null;
  room_id: string | null;
  target_user_id: string | null;
  target_quiz_set_id: string | null;
  reason: string;
  details: string | null;
  status: ReportStatus;
  created_at: string;
  reviewed_by: string | null;
  reviewed_at: string | null;
}

export interface ReportTarget {
  kind: 'user' | 'quiz_set' | 'room';
  id: string;
  label: string | null;
}

export interface ReportQueueItem {
  report: ReportResponse;
  target: ReportTarget | null;
}

export interface ReportQueueResponse {
  items: ReportQueueItem[];
  limit: number;
  offset: number;
}

export interface DecisionRequest {
  decision: DecisionAction;
  reason?: string | null;
}

export interface DecisionResponse {
  report_id: string;
  decision: DecisionAction;
  status: ReportStatus;
}

// ---------------------------------------------------------------------------
// Error envelope
// ---------------------------------------------------------------------------

export interface ApiErrorBody {
  error: {
    code: string;
    message: string;
    details?: Record<string, unknown>;
  };
  request_id?: string;
}

// ---------------------------------------------------------------------------
// WebSocket protocol (mirrors backend/app/ws/messages.py)
// ---------------------------------------------------------------------------

export interface WsEnvelope<TType extends string, TPayload> {
  type: TType;
  message_id?: string | null;
  room_code?: string;
  match_id?: string;
  sent_at?: string;
  payload: TPayload;
}

// --- client -> server ---

export type ClientHeartbeat = WsEnvelope<'room.heartbeat', { last_seen_event_id?: string | null }>;
export type ClientAnswerSubmit = WsEnvelope<
  'answer.submit',
  {
    match_id: string;
    match_question_id: string;
    selected_option_ids: string[];
    client_sent_at?: string | null;
  }
>;
export type ClientHostQuestionNext = WsEnvelope<
  'host.question.next',
  { expected_current_position: number }
>;
export type ClientHostMatchPause = WsEnvelope<'host.match.pause', { reason?: string | null }>;

export type ClientMessage =
  | ClientHeartbeat
  | ClientAnswerSubmit
  | ClientHostQuestionNext
  | ClientHostMatchPause;

export type ClientMessageType = ClientMessage['type'];

// --- server -> client ---

export interface RoomSnapshotPayload {
  room: RoomSnapshotRoom;
  participants: RoomSnapshotParticipant[];
  match: RoomSnapshotMatch | null;
  leaderboard: LeaderboardEntry[];
}

export interface HeartbeatAckPayload {
  server_now: string;
  last_seen_event_id?: string | null;
}

export interface ParticipantJoinedPayload {
  participant_id: string;
  nickname: string;
  player_count: number;
}

export type ParticipantLeftPayload = ParticipantJoinedPayload;

export interface MatchStartedPayload {
  match_id: string;
  question_count: number;
  server_now: string;
}

export interface QuestionStartedOption {
  id: string;
  body: string;
}

export interface QuestionStartedQuestion {
  body: string;
  type: QuestionType | string;
  options: QuestionStartedOption[];
}

export interface QuestionStartedPayload {
  match_question_id: string;
  position: number;
  question: QuestionStartedQuestion;
  started_at: string;
  deadline_at: string;
  server_now: string;
}

export interface AnswerAcceptedPayload {
  submission_id: string;
  accepted: boolean;
  score_awarded: number;
  response_time_ms: number;
}

export interface LeaderboardUpdatedPayload {
  version: number;
  top: LeaderboardEntry[];
}

export interface QuestionClosedPayload {
  match_question_id: string;
  correct_option_ids: string[];
  explanation: string | null;
  accuracy_percent: number | null;
}

export interface MatchFinishedPayload {
  match_id: string;
  final_leaderboard_url: string;
  analytics_url: string | null;
}

export interface WsErrorPayload {
  code: string;
  message: string | null;
  retry_after_ms: number | null;
}

export type ServerRoomSnapshot = WsEnvelope<'room.snapshot', RoomSnapshotPayload>;
export type ServerHeartbeatAck = WsEnvelope<'room.heartbeat.ack', HeartbeatAckPayload>;
export type ServerParticipantJoined = WsEnvelope<'participant.joined', ParticipantJoinedPayload>;
export type ServerParticipantLeft = WsEnvelope<'participant.left', ParticipantLeftPayload>;
export type ServerMatchStarted = WsEnvelope<'match.started', MatchStartedPayload>;
export type ServerQuestionStarted = WsEnvelope<'question.started', QuestionStartedPayload>;
export type ServerAnswerAccepted = WsEnvelope<'answer.accepted', AnswerAcceptedPayload>;
export type ServerLeaderboardUpdated = WsEnvelope<'leaderboard.updated', LeaderboardUpdatedPayload>;
export type ServerQuestionClosed = WsEnvelope<'question.closed', QuestionClosedPayload>;
export type ServerMatchFinished = WsEnvelope<'match.finished', MatchFinishedPayload>;
export type ServerError = WsEnvelope<'error', WsErrorPayload>;

export type ServerMessage =
  | ServerRoomSnapshot
  | ServerHeartbeatAck
  | ServerParticipantJoined
  | ServerParticipantLeft
  | ServerMatchStarted
  | ServerQuestionStarted
  | ServerAnswerAccepted
  | ServerLeaderboardUpdated
  | ServerQuestionClosed
  | ServerMatchFinished
  | ServerError;

export type ServerMessageType = ServerMessage['type'];
