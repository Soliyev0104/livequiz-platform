# A. Leaderboard Load Test

## Config

- players: 2
- questions: 1
- base_url: http://localhost:8888
- api_prefix: /api/v1
- observed LEADERBOARD_BACKEND: redis

## Results

| metric | n | min_ms | p50_ms | p95_ms | max_ms |
| --- | ---: | ---: | ---: | ---: | ---: |
| join_ms | 2 | 18.8 | 153.3 | 274.4 | 287.9 |
| answer_ms | 2 | 23.3 | 31.7 | 39.3 | 40.2 |
| leaderboard_ms | 2 | 7.8 | 9.8 | 11.5 | 11.7 |

## How to reproduce the before run

Bring up api-a/api-b with `LEADERBOARD_BACKEND=pg`, restart the API containers so settings reload, rerun this script with the same arguments, then paste the second table alongside this one as `before (pg)` vs `after (redis)`.
