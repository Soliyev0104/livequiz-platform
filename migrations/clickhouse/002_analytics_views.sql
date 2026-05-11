-- Analytics materialized views.
--
-- The MV writes a pre-aggregated row per AnswerSubmitted insert so the
-- analytics endpoint can read accuracy without scanning every event.
-- SummingMergeTree merges duplicate (match_id, question_id) keys by
-- summing the metric columns.

CREATE MATERIALIZED VIEW IF NOT EXISTS livequiz.question_accuracy_mv
ENGINE = SummingMergeTree
PARTITION BY toYYYYMM(occurred_at)
ORDER BY (match_id, question_id)
AS
SELECT
    match_id,
    question_id,
    count() AS total_answers,
    sum(is_correct) AS correct_answers,
    sum(response_time_ms) AS response_time_sum_ms,
    occurred_at
FROM livequiz.answer_events
GROUP BY match_id, question_id, occurred_at;
