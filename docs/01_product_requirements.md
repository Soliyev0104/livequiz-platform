# Product Requirements

## Product vision

LiveQuiz lets a host create quiz sets, open a live game room, invite players with a room code, run timed questions, display a real-time leaderboard, and review post-match analytics. It also includes moderation tools so reported or suspicious content can be reviewed by admins.

## Actors

- **Guest player**: joins room using code and nickname, answers questions, sees leaderboard.
- **Registered player**: same as guest but has persistent profile and history.
- **Host/teacher**: creates quiz sets, starts rooms, controls match flow.
- **Moderator/admin**: reviews flagged content, bans abusive users/nicknames, hides problematic quiz content.
- **System worker**: processes events, analytics, moderation heuristics, and outbox publishing.

## Core use cases

### UC1 — Host creates a quiz set

1. Host logs in.
2. Host creates a quiz set with title, description, category, visibility, and tags.
3. Host adds questions with answer options and correct answers.
4. System validates at least two options and exactly one or more correct options depending on question type.
5. Quiz set becomes draft or published.

### UC2 — Host opens a live room

1. Host selects a published quiz set.
2. Host chooses room settings: max players, question timer, scoring mode, public/private, nickname rules.
3. System creates a room code and room state.
4. Players can join before the match starts.

### UC3 — Player joins and plays

1. Player enters room code and nickname.
2. System validates capacity, room state, nickname moderation, and rate limits.
3. Player receives current room snapshot through WebSocket.
4. For each question, player submits answer before deadline.
5. System accepts only the first valid answer per player per question, scores it, updates leaderboard, and broadcasts changes.

### UC4 — Host controls match

1. Host starts match.
2. Server creates match rows and question sequence.
3. Server broadcasts question start with authoritative `deadline_at`.
4. Host can pause, resume, skip, or end match depending on permissions.
5. At end, system persists final leaderboard and marks room completed.

### UC5 — Post-match analytics

1. After match ends, events are processed by the stream worker.
2. ClickHouse stores answer events and match metrics.
3. Host opens analytics dashboard showing accuracy by question, average response time, drop-off, top players, and most missed questions.
4. Admin can view platform-level daily metrics.

### UC6 — Moderation workflow

1. System flags suspicious nickname/question text/chat message using keyword rules.
2. Players or hosts can report content.
3. Moderators review queue and take action: dismiss, hide content, mute player, ban user, or ban room nickname.
4. All decisions are audit-logged.

## Functional requirements

- Authentication with access/refresh JWT tokens.
- Roles: player, host, moderator, admin.
- Quiz-set CRUD with questions and answer options.
- Room code join flow for guest and registered players.
- WebSocket real-time room events.
- Timed questions controlled by server timestamps.
- Scoring by correctness and response speed.
- Live leaderboard.
- Post-match analytics.
- Content moderation queue and report flow.
- Admin dashboard for key platform metrics.

## Non-functional requirements

| Area | Target |
|---|---|
| Availability | Local demo must survive service restarts except active WS connections; production target 99%+ for course demo. |
| Latency | Join room < 500 ms p95; answer acceptance < 200 ms p95 inside same VM; leaderboard broadcast < 500 ms p95. |
| Consistency | Strong uniqueness for answer submissions; room analytics eventual within seconds. |
| Scalability | 100 rooms, 50 players per room locally as demo target; architecture should extend horizontally with API replicas. |
| Security | Password hashing, JWT auth, role checks, input validation, CORS, rate limits, no secret commits. |
| Observability | Every user action traceable with request ID; logs and metrics correlated in Grafana. |

## MVP scope

Build live quiz rooms, timed questions, scoring, leaderboard, analytics, and moderation. Avoid payments, mobile app, voice/video chat, complex social graph, and external AI moderation for v1.
