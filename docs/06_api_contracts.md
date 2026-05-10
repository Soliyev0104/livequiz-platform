# REST API Contracts

Base path: `/api/v1`.

Swagger/OpenAPI must be served at `/api/docs` through Nginx.

## Conventions

### Auth header

```http
Authorization: Bearer <access_token>
```

### Idempotency header

Use for mutating gameplay actions where retries can happen:

```http
X-Request-ID: <uuid-or-client-generated-id>
```

### Error response

```json
{
  "error": {
    "code": "ROOM_NOT_FOUND",
    "message": "Room code does not exist",
    "details": {}
  },
  "request_id": "req_..."
}
```

## Endpoint table

| Method | Path | Auth | Purpose |
|---|---|---:|---|
| GET | `/health` | No | Liveness. |
| GET | `/ready` | No | DB/Redis readiness. |
| POST | `/auth/register` | No | Register user. |
| POST | `/auth/login` | No | Issue tokens. |
| POST | `/auth/refresh` | No | Refresh access token. |
| POST | `/auth/logout` | Yes | Revoke refresh token. |
| GET | `/me` | Yes | Current profile. |
| GET | `/quiz-sets` | Optional | Search/list public or own quiz sets. |
| POST | `/quiz-sets` | Host | Create quiz set. |
| GET | `/quiz-sets/{id}` | Owner/public | Get quiz set with questions. |
| PATCH | `/quiz-sets/{id}` | Owner | Update metadata. |
| POST | `/quiz-sets/{id}/publish` | Owner | Publish quiz set. |
| POST | `/quiz-sets/{id}/questions` | Owner | Add question. |
| PATCH | `/questions/{id}` | Owner | Update question. |
| DELETE | `/questions/{id}` | Owner | Delete question. |
| POST | `/rooms` | Host | Create live room. |
| GET | `/rooms/{code}` | Optional | Get room snapshot. |
| POST | `/rooms/{code}/join` | Optional | Join as player/guest. |
| POST | `/rooms/{code}/start` | Host | Start match. |
| POST | `/rooms/{code}/pause` | Host | Pause match. |
| POST | `/rooms/{code}/resume` | Host | Resume match. |
| POST | `/rooms/{code}/end` | Host | End match. |
| POST | `/matches/{match_id}/answers` | Participant | Submit answer, REST fallback for WS. |
| GET | `/matches/{match_id}/leaderboard` | Participant/host | Current or final leaderboard. |
| GET | `/matches/{match_id}/analytics` | Host | Post-match analytics from ClickHouse. |
| POST | `/reports` | Auth/guest token | Report content/player. |
| GET | `/moderation/reports` | Moderator | Review queue. |
| POST | `/moderation/reports/{id}/decision` | Moderator | Dismiss/action. |
| GET | `/admin/metrics` | Admin | Platform metrics. |

## Example payloads

### Register

`POST /api/v1/auth/register`

```json
{
  "email": "host@livequiz.local",
  "password": "StrongPassword123!",
  "display_name": "Avenger Host"
}
```

Response `201`:

```json
{
  "id": "738510928471040000",
  "email": "host@livequiz.local",
  "display_name": "Avenger Host",
  "role": "host"
}
```

### Create quiz set

`POST /api/v1/quiz-sets`

```json
{
  "title": "Computer Networks Quiz",
  "description": "Subnetting, routing, DNS, HTTP",
  "visibility": "private",
  "tags": ["networks", "exam-prep"]
}
```

Response `201`:

```json
{
  "id": "738510981232640000",
  "title": "Computer Networks Quiz",
  "is_published": false,
  "version": 1,
  "question_count": 0
}
```

### Add question

`POST /api/v1/quiz-sets/{id}/questions`

```json
{
  "position": 1,
  "body": "Which transport protocol is connectionless?",
  "type": "single_choice",
  "time_limit_seconds": 20,
  "points": 1000,
  "options": [
    {"position": 1, "body": "TCP", "is_correct": false},
    {"position": 2, "body": "UDP", "is_correct": true},
    {"position": 3, "body": "HTTP", "is_correct": false},
    {"position": 4, "body": "TLS", "is_correct": false}
  ],
  "explanation": "UDP is connectionless and does not establish a session before sending datagrams."
}
```

### Create room

`POST /api/v1/rooms`

```json
{
  "quiz_set_id": "738510981232640000",
  "max_players": 50,
  "settings": {
    "scoring_mode": "speed_bonus",
    "show_correct_after_each_question": true,
    "allow_guests": true,
    "question_timer_seconds": 20
  }
}
```

Response `201`:

```json
{
  "room_id": "738511241389260800",
  "code": "K7Q2M9",
  "status": "lobby",
  "host_ws_url": "/ws/rooms/K7Q2M9?token=..."
}
```

### Join room

`POST /api/v1/rooms/{code}/join`

```json
{
  "nickname": "Avenger",
  "guest_id": "optional-client-uuid"
}
```

Response `200`:

```json
{
  "participant_id": "738511300977209344",
  "room_id": "738511241389260800",
  "code": "K7Q2M9",
  "nickname": "Avenger",
  "participant_token": "guest_or_jwt_scoped_token",
  "ws_url": "/ws/rooms/K7Q2M9?token=..."
}
```

### Submit answer

`POST /api/v1/matches/{match_id}/answers`

Headers: `X-Request-ID: 0202d1c7-431a-4e74-903b-5b3f5a75f3b8`

```json
{
  "match_question_id": "738511555098206208",
  "selected_option_ids": ["738511553890127872"],
  "client_sent_at": "2026-05-10T10:20:33.120Z"
}
```

Response `202`:

```json
{
  "submission_id": "738511559401627648",
  "accepted": true,
  "is_correct": true,
  "score_awarded": 915,
  "response_time_ms": 1700,
  "leaderboard_rank": 2
}
```

## Error codes

| Code | HTTP | Meaning |
|---|---:|---|
| `AUTH_REQUIRED` | 401 | Missing/invalid token. |
| `FORBIDDEN` | 403 | Role/ownership violation. |
| `QUIZ_NOT_PUBLISHED` | 409 | Cannot create room from draft quiz. |
| `ROOM_NOT_FOUND` | 404 | Invalid room code. |
| `ROOM_FULL` | 409 | Capacity reached. |
| `ROOM_NOT_JOINABLE` | 409 | Match already running or completed. |
| `DUPLICATE_NICKNAME` | 409 | Nickname taken in room. |
| `QUESTION_CLOSED` | 409 | Deadline passed. |
| `ANSWER_ALREADY_SUBMITTED` | 409 | Unique answer already exists. |
| `RATE_LIMITED` | 429 | Too many requests/messages. |
| `VALIDATION_ERROR` | 422 | Pydantic validation failed. |
