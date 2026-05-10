# WebSocket Protocol

Endpoint:

```text
/ws/rooms/{room_code}?token=<jwt-or-participant-token>
```

WebSockets are used because the room needs server-pushed events: player joins/leaves, match starts, question starts, answer acceptance, leaderboard updates, and match finish. REST remains for CRUD and fallback.

## Envelope

Every message uses one JSON envelope.

```json
{
  "type": "question.started",
  "message_id": "738511600200499200",
  "room_code": "K7Q2M9",
  "match_id": "738511500123456789",
  "sent_at": "2026-05-10T10:21:00.000Z",
  "payload": {}
}
```

## Client → server messages

### `room.heartbeat`

```json
{
  "type": "room.heartbeat",
  "message_id": "client-uuid",
  "payload": {"last_seen_event_id": "738511600200499200"}
}
```

### `answer.submit`

```json
{
  "type": "answer.submit",
  "message_id": "client-uuid-idempotency-key",
  "payload": {
    "match_id": "738511500123456789",
    "match_question_id": "738511555098206208",
    "selected_option_ids": ["738511553890127872"],
    "client_sent_at": "2026-05-10T10:21:05.210Z"
  }
}
```

### `host.question.next`

```json
{
  "type": "host.question.next",
  "message_id": "client-uuid",
  "payload": {"expected_current_position": 2}
}
```

### `host.match.pause`

```json
{
  "type": "host.match.pause",
  "message_id": "client-uuid",
  "payload": {"reason": "short break"}
}
```

## Server → client messages

### `room.snapshot`

Sent immediately after connect and after reconnect.

```json
{
  "type": "room.snapshot",
  "message_id": "738511610000000000",
  "payload": {
    "room": {"code": "K7Q2M9", "status": "lobby", "player_count": 12},
    "participants": [{"participant_id": "...", "nickname": "Avenger", "online": true}],
    "match": null,
    "leaderboard": []
  }
}
```

### `participant.joined`

```json
{
  "type": "participant.joined",
  "payload": {"participant_id": "...", "nickname": "Azamat", "player_count": 13}
}
```

### `match.started`

```json
{
  "type": "match.started",
  "payload": {
    "match_id": "738511500123456789",
    "question_count": 10,
    "server_now": "2026-05-10T10:22:00.000Z"
  }
}
```

### `question.started`

```json
{
  "type": "question.started",
  "payload": {
    "match_question_id": "738511555098206208",
    "position": 1,
    "question": {
      "body": "Which transport protocol is connectionless?",
      "type": "single_choice",
      "options": [
        {"id": "7385115531", "body": "TCP"},
        {"id": "7385115532", "body": "UDP"}
      ]
    },
    "started_at": "2026-05-10T10:22:05.000Z",
    "deadline_at": "2026-05-10T10:22:25.000Z",
    "server_now": "2026-05-10T10:22:05.010Z"
  }
}
```

Do not send correct answers in `question.started`.

### `answer.accepted`

Private to the player.

```json
{
  "type": "answer.accepted",
  "payload": {
    "submission_id": "738511559401627648",
    "accepted": true,
    "score_awarded": 915,
    "response_time_ms": 1700
  }
}
```

### `leaderboard.updated`

```json
{
  "type": "leaderboard.updated",
  "payload": {
    "version": 7,
    "top": [
      {"rank": 1, "participant_id": "...", "nickname": "Marvel", "score": 2410},
      {"rank": 2, "participant_id": "...", "nickname": "Avenger", "score": 2280}
    ]
  }
}
```

### `question.closed`

```json
{
  "type": "question.closed",
  "payload": {
    "match_question_id": "738511555098206208",
    "correct_option_ids": ["7385115532"],
    "explanation": "UDP is connectionless.",
    "accuracy_percent": 71.4
  }
}
```

### `match.finished`

```json
{
  "type": "match.finished",
  "payload": {
    "match_id": "738511500123456789",
    "final_leaderboard_url": "/api/v1/matches/738511500123456789/leaderboard",
    "analytics_url": "/api/v1/matches/738511500123456789/analytics"
  }
}
```

## Redis pub/sub across API replicas

All API replicas subscribe to `ws:room:{code}`. If API A updates a leaderboard, it publishes to Redis; API B receives the message and forwards it to its connected clients. This avoids sticky sessions as a hard requirement.

## Reconnect strategy

- Client reconnects with token and last seen event ID.
- Server sends `room.snapshot` from Redis/Postgres.
- If match is running, snapshot includes current question and deadline.
- Client resumes local countdown based on server timestamps.

## Rate limits

- Join room: 10 attempts/minute/IP.
- Answer submit: 5 attempts/question/participant, but only first valid one is accepted.
- Host control: 60 actions/minute/host.
- Heartbeat: expected every 20 seconds; disconnect after 60 seconds silence.
