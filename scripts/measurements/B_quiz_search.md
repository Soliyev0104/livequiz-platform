# Measurement B — Quiz search

Dataset: **20000** quiz_sets rows. Each phase ran the same query **10** times.

Query:

```sql
EXPLAIN (ANALYZE, BUFFERS) SELECT * FROM quiz_sets WHERE title ILIKE '%network%' LIMIT 20
```

## Timings

| Phase | min ms | p50 ms | p95 ms | max ms | scan type |
|---|---:|---:|---:|---:|---|
| before | 0.051 | 0.055 | 0.059 | 0.083 | Seq Scan |
| after | 0.359 | 0.389 | 0.473 | 0.482 | Bitmap Index Scan (GIN trigram) |

## Plan — before (no trigram index)

```
Limit  (cost=0.00..3.44 rows=20 width=99) (actual time=0.010..0.049 rows=20 loops=1)
  Buffers: shared hit=2
  ->  Seq Scan on quiz_sets  (cost=0.00..520.00 rows=3022 width=99) (actual time=0.009..0.047 rows=20 loops=1)
        Filter: ((title)::text ~~* '%network%'::text)
        Rows Removed by Filter: 90
        Buffers: shared hit=2
Planning:
  Buffers: shared hit=58
Planning Time: 0.483 ms
Execution Time: 0.059 ms
```

## Plan — after (`ix_quiz_sets_title_trgm` present)

```
Limit  (cost=67.53..69.56 rows=20 width=99) (actual time=0.326..0.337 rows=20 loops=1)
  Buffers: shared hit=18
  ->  Bitmap Heap Scan on quiz_sets  (cost=67.53..375.30 rows=3022 width=99) (actual time=0.325..0.335 rows=20 loops=1)
        Recheck Cond: ((title)::text ~~* '%network%'::text)
        Heap Blocks: exact=2
        Buffers: shared hit=18
        ->  Bitmap Index Scan on ix_quiz_sets_title_trgm  (cost=0.00..66.77 rows=3022 width=0) (actual time=0.298..0.298 rows=3022 loops=1)
              Index Cond: ((title)::text ~~* '%network%'::text)
              Buffers: shared hit=16
Planning:
  Buffers: shared hit=25
Planning Time: 0.331 ms
Execution Time: 0.386 ms
```
