# Frontend UI/UX Specification

## Goal

Build a polished, modern multiplayer experience. It should feel like Kahoot-style live rooms but with a cleaner dashboard and a serious analytics panel.

## Stack

Recommended:

- Next.js + TypeScript, or Vite React + TypeScript.
- Tailwind CSS.
- shadcn-style components.
- Framer Motion for room/game transitions.
- Recharts for analytics charts.
- TanStack Query for REST data.
- Native WebSocket wrapper for live room events.

## Visual direction

- Dark-first dashboard with optional light mode.
- Large room code, high contrast, animated status badges.
- Quiz playing screen must be distraction-free: question, options, timer, answer confirmation.
- Use cards, rounded corners, soft shadows, gradients, and clear hierarchy.
- Do not make tables ugly; use compact cards for players and analytics.

## Pages

### `/`

Landing page:

- Hero: “Host real-time quizzes with live leaderboards.”
- Buttons: Join Room, Create Quiz, Sign In.
- Demo room preview.
- Feature cards: real-time rooms, analytics, moderation.

### `/login`, `/register`

- Clean auth forms.
- Show demo credentials.

### `/dashboard`

Host dashboard:

- My quiz sets.
- Recent rooms.
- Create quiz button.
- Analytics summary cards.

### `/quiz-sets/new` and `/quiz-sets/[id]/edit`

Quiz builder:

- Left: question list.
- Center: selected question editor.
- Right: settings/validation panel.
- Support add/reorder/delete questions.
- Option editor with correct answer toggle.
- Publish validation checklist.

### `/host/rooms/[code]`

Host lobby/control:

- Big room code.
- Player list with live join animation.
- Start button disabled until at least one player and quiz has questions.
- During match: current question, timer, answer count, next/skip/end controls, leaderboard.

### `/join`

- Room code input.
- Nickname input.
- Recent joined room optional.

### `/play/[code]`

Player live room:

- Lobby waiting screen.
- Question screen with big answer buttons.
- Timer bar.
- Answer accepted/too late feedback.
- Between questions leaderboard.
- Final results with rank and score.

### `/matches/[id]/analytics`

Host analytics:

- Final leaderboard.
- Question accuracy bar chart.
- Response-time distribution.
- Most missed questions.
- Export/share screenshot section.

### `/moderation`

Moderator queue:

- Pending reports.
- Context preview.
- Actions: dismiss, hide, mute, ban.
- Audit trail.

## State management

- Use TanStack Query for REST resources.
- Use local reducer/Zustand for live match state from WebSocket messages.
- Treat WebSocket messages as patches over last `room.snapshot`.
- On reconnect, call REST `GET /rooms/{code}` and wait for `room.snapshot`.

## WebSocket client behavior

- Exponential reconnect: 500 ms, 1s, 2s, 5s max.
- Heartbeat every 20 seconds.
- Show “Reconnecting…” overlay but keep current question visible.
- If deadline passes while disconnected, show “Connection lost — answer may not count.”

## UX details that impress

- Copy room code button with toast.
- QR code for room join URL.
- Local countdown synchronized with server timestamp.
- Leaderboard position animation.
- Confetti only for match winner, not overused.
- Skeleton loading for dashboard cards.
- Empty states with clear call-to-action.
- Keyboard shortcuts for host: Space = next question, Esc = pause.

## Accessibility

- Buttons must have visible focus states.
- Answer options should be keyboard-selectable.
- Do not rely only on color for correct/incorrect state.
- Use readable fonts and 16px+ body text.
