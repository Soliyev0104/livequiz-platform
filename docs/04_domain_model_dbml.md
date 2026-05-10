# Domain Model and DBML

This ERD must be hand-designed for the report. Do not rely only on ORM-generated diagrams.

```dbml
Enum user_role {
  player
  host
  moderator
  admin
}

Enum quiz_visibility {
  private
  unlisted
  public
}

Enum room_status {
  lobby
  running
  paused
  completed
  cancelled
}

Enum question_type {
  single_choice
  multiple_choice
  true_false
}

Enum moderation_status {
  pending
  dismissed
  action_taken
}

Table users {
  id bigint [pk]
  email varchar(255) [unique, not null]
  password_hash text [not null]
  display_name varchar(80) [not null]
  role user_role [not null, default: 'player']
  is_active boolean [not null, default: true]
  created_at timestamptz [not null]
  updated_at timestamptz [not null]
}

Table quiz_sets {
  id bigint [pk]
  owner_id bigint [not null, ref: > users.id]
  title varchar(160) [not null]
  description text
  visibility quiz_visibility [not null, default: 'private']
  is_published boolean [not null, default: false]
  version int [not null, default: 1]
  created_at timestamptz [not null]
  updated_at timestamptz [not null]
}

Table quiz_tags {
  id bigint [pk]
  name varchar(60) [unique, not null]
}

Table quiz_set_tags {
  quiz_set_id bigint [not null, ref: > quiz_sets.id]
  tag_id bigint [not null, ref: > quiz_tags.id]

  indexes {
    (quiz_set_id, tag_id) [pk]
  }
}

Table questions {
  id bigint [pk]
  quiz_set_id bigint [not null, ref: > quiz_sets.id]
  position int [not null]
  body text [not null]
  type question_type [not null]
  time_limit_seconds int [not null, default: 20]
  points int [not null, default: 1000]
  explanation text
  created_at timestamptz [not null]
  updated_at timestamptz [not null]

  indexes {
    (quiz_set_id, position) [unique]
  }
}

Table answer_options {
  id bigint [pk]
  question_id bigint [not null, ref: > questions.id]
  position int [not null]
  body text [not null]
  is_correct boolean [not null, default: false]

  indexes {
    (question_id, position) [unique]
  }
}

Table rooms {
  id bigint [pk]
  code varchar(12) [unique, not null]
  host_id bigint [not null, ref: > users.id]
  quiz_set_id bigint [not null, ref: > quiz_sets.id]
  status room_status [not null, default: 'lobby']
  max_players int [not null, default: 50]
  settings jsonb [not null, default: '{}']
  created_at timestamptz [not null]
  started_at timestamptz
  ended_at timestamptz

  indexes {
    code
    (host_id, created_at)
  }
}

Table room_participants {
  id bigint [pk]
  room_id bigint [not null, ref: > rooms.id]
  user_id bigint [ref: > users.id]
  nickname varchar(60) [not null]
  guest_token_hash text
  joined_at timestamptz [not null]
  left_at timestamptz
  is_kicked boolean [not null, default: false]

  indexes {
    (room_id, nickname) [unique]
    (room_id, user_id)
  }
}

Table matches {
  id bigint [pk]
  room_id bigint [unique, not null, ref: > rooms.id]
  quiz_set_version int [not null]
  status room_status [not null]
  started_at timestamptz [not null]
  ended_at timestamptz
}

Table match_questions {
  id bigint [pk]
  match_id bigint [not null, ref: > matches.id]
  question_id bigint [not null, ref: > questions.id]
  position int [not null]
  started_at timestamptz
  deadline_at timestamptz
  closed_at timestamptz

  indexes {
    (match_id, position) [unique]
  }
}

Table answer_submissions {
  id bigint [pk]
  match_id bigint [not null, ref: > matches.id]
  match_question_id bigint [not null, ref: > match_questions.id]
  participant_id bigint [not null, ref: > room_participants.id]
  selected_option_ids bigint[] [not null]
  is_correct boolean [not null]
  score_awarded int [not null]
  response_time_ms int [not null]
  submitted_at timestamptz [not null]
  request_id varchar(80) [not null]

  indexes {
    (match_question_id, participant_id) [unique]
    (match_id, participant_id)
    request_id [unique]
  }
}

Table final_scores {
  match_id bigint [not null, ref: > matches.id]
  participant_id bigint [not null, ref: > room_participants.id]
  total_score int [not null]
  correct_count int [not null]
  average_response_ms int
  rank int [not null]

  indexes {
    (match_id, participant_id) [pk]
    (match_id, rank)
  }
}

Table moderation_reports {
  id bigint [pk]
  reporter_user_id bigint [ref: > users.id]
  room_id bigint [ref: > rooms.id]
  target_user_id bigint [ref: > users.id]
  target_quiz_set_id bigint [ref: > quiz_sets.id]
  reason varchar(120) [not null]
  details text
  status moderation_status [not null, default: 'pending']
  created_at timestamptz [not null]
  reviewed_by bigint [ref: > users.id]
  reviewed_at timestamptz
}

Table audit_logs {
  id bigint [pk]
  actor_user_id bigint [ref: > users.id]
  action varchar(120) [not null]
  entity_type varchar(80) [not null]
  entity_id bigint
  metadata jsonb [not null, default: '{}']
  created_at timestamptz [not null]
}

Table outbox_events {
  id bigint [pk]
  aggregate_type varchar(80) [not null]
  aggregate_id bigint [not null]
  event_type varchar(120) [not null]
  payload jsonb [not null]
  occurred_at timestamptz [not null]
  published_at timestamptz
  publish_attempts int [not null, default: 0]

  indexes {
    (published_at, occurred_at)
    (aggregate_type, aggregate_id)
  }
}
```

## Important relationships

- One user can own many quiz sets.
- One quiz set contains many ordered questions.
- One question contains many ordered answer options.
- One room is created from one quiz set and belongs to one host.
- One room has many participants.
- One room has at most one active match.
- One match has many match questions.
- One participant can submit at most one answer per match question.
- Final scores are materialized after match completion.
- Outbox events are linked to aggregate type and aggregate ID for event replay and debugging.
