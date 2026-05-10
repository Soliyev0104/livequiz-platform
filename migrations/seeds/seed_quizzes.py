"""Seed three demo quiz sets (Computer Networks, Databases, General Knowledge).

Each quiz has 8–12 questions and 2–4 answer options. Idempotent on quiz
title for the host-owned quiz sets, and on tag name. Returns a map of quiz
title → QuizSet for downstream seeders (e.g. demo room).
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ids import get_id_generator
from app.db.models.answer_option import AnswerOption
from app.db.models.enums import QuestionType, QuizVisibility
from app.db.models.question import Question
from app.db.models.quiz_set import QuizSet
from app.db.models.quiz_set_tag import QuizSetTag
from app.db.models.quiz_tag import QuizTag
from app.db.models.user import User

# (text, type, options[(body, is_correct)], explanation?)
QuestionSpec = tuple[str, QuestionType, list[tuple[str, bool]], str | None]


NETWORKS: list[QuestionSpec] = [
    (
        "Which OSI layer is responsible for end-to-end delivery?",
        QuestionType.single_choice,
        [
            ("Network", False),
            ("Transport", True),
            ("Session", False),
            ("Data Link", False),
        ],
        "TCP/UDP live at the transport layer.",
    ),
    (
        "TCP is connection-oriented.",
        QuestionType.true_false,
        [("True", True), ("False", False)],
        None,
    ),
    (
        "Which protocols operate primarily over UDP? (choose all)",
        QuestionType.multiple_choice,
        [("DNS", True), ("HTTP/1.1", False), ("QUIC", True), ("FTP", False)],
        "DNS uses UDP/53 by default; QUIC is built on UDP.",
    ),
    (
        "What is the default TLS port for HTTPS?",
        QuestionType.single_choice,
        [("80", False), ("8080", False), ("443", True), ("21", False)],
        None,
    ),
    (
        "An IPv4 address is how many bits wide?",
        QuestionType.single_choice,
        [("16", False), ("32", True), ("64", False), ("128", False)],
        None,
    ),
    (
        "ARP resolves IPv4 addresses to MAC addresses.",
        QuestionType.true_false,
        [("True", True), ("False", False)],
        None,
    ),
    (
        "Which fields appear in a TCP header? (choose all)",
        QuestionType.multiple_choice,
        [
            ("Source port", True),
            ("Sequence number", True),
            ("TTL", False),
            ("Window size", True),
        ],
        "TTL is in the IP header, not TCP.",
    ),
    (
        "CIDR /24 covers how many host addresses (excluding network/broadcast)?",
        QuestionType.single_choice,
        [("254", True), ("256", False), ("510", False), ("128", False)],
        None,
    ),
    (
        "DNS records that map a name to an IPv6 address are called…",
        QuestionType.single_choice,
        [("A", False), ("AAAA", True), ("CNAME", False), ("MX", False)],
        None,
    ),
    (
        "BGP is an interior gateway protocol.",
        QuestionType.true_false,
        [("True", False), ("False", True)],
        "BGP is exterior; OSPF and RIP are interior.",
    ),
]


DATABASES: list[QuestionSpec] = [
    (
        "Which property of ACID guarantees that committed data survives crashes?",
        QuestionType.single_choice,
        [
            ("Atomicity", False),
            ("Consistency", False),
            ("Isolation", False),
            ("Durability", True),
        ],
        None,
    ),
    (
        "A B+ tree index is typically used for range scans.",
        QuestionType.true_false,
        [("True", True), ("False", False)],
        None,
    ),
    (
        "Which isolation levels prevent dirty reads? (choose all)",
        QuestionType.multiple_choice,
        [
            ("Read uncommitted", False),
            ("Read committed", True),
            ("Repeatable read", True),
            ("Serializable", True),
        ],
        None,
    ),
    (
        "In Postgres, which command rebuilds index statistics?",
        QuestionType.single_choice,
        [
            ("VACUUM", False),
            ("ANALYZE", True),
            ("REINDEX", False),
            ("CLUSTER", False),
        ],
        None,
    ),
    (
        "A foreign key always implies an index on the referencing column.",
        QuestionType.true_false,
        [("True", False), ("False", True)],
        "Postgres does not auto-create an index for the referencing side.",
    ),
    (
        "Which normal form removes transitive dependencies?",
        QuestionType.single_choice,
        [("1NF", False), ("2NF", False), ("3NF", True), ("BCNF", False)],
        None,
    ),
    (
        "Which of these are valid index types in Postgres? (choose all)",
        QuestionType.multiple_choice,
        [("B-tree", True), ("GIN", True), ("BRIN", True), ("R-tree", False)],
        None,
    ),
    (
        "A composite primary key counts as one constraint at the table level.",
        QuestionType.true_false,
        [("True", True), ("False", False)],
        None,
    ),
    (
        "What does the SQL `EXPLAIN ANALYZE` clause add over plain `EXPLAIN`?",
        QuestionType.single_choice,
        [
            ("Pretty-print only", False),
            ("Actual run timings", True),
            ("Schema validation", False),
            ("Locks", False),
        ],
        None,
    ),
]


GENERAL: list[QuestionSpec] = [
    (
        "Which planet is the largest in our solar system?",
        QuestionType.single_choice,
        [
            ("Earth", False),
            ("Saturn", False),
            ("Jupiter", True),
            ("Neptune", False),
        ],
        None,
    ),
    (
        "The Pacific Ocean is larger than all land combined.",
        QuestionType.true_false,
        [("True", True), ("False", False)],
        None,
    ),
    (
        "Which of these are programming languages? (choose all)",
        QuestionType.multiple_choice,
        [("Rust", True), ("Markdown", False), ("Python", True), ("Kotlin", True)],
        None,
    ),
    (
        "Who wrote the play 'Hamlet'?",
        QuestionType.single_choice,
        [
            ("Shakespeare", True),
            ("Tolstoy", False),
            ("Dostoevsky", False),
            ("Marlowe", False),
        ],
        None,
    ),
    (
        "Mount Everest is the tallest mountain measured from sea level.",
        QuestionType.true_false,
        [("True", True), ("False", False)],
        None,
    ),
    (
        "Which gas do plants primarily absorb during photosynthesis?",
        QuestionType.single_choice,
        [("Oxygen", False), ("Carbon dioxide", True), ("Nitrogen", False), ("Methane", False)],
        None,
    ),
    (
        "Which of these countries border France? (choose all)",
        QuestionType.multiple_choice,
        [("Spain", True), ("Italy", True), ("Portugal", False), ("Belgium", True)],
        None,
    ),
    (
        "How many bits are in a byte?",
        QuestionType.single_choice,
        [("4", False), ("8", True), ("16", False), ("32", False)],
        None,
    ),
]


QUIZZES: list[tuple[str, str, list[str], list[QuestionSpec]]] = [
    (
        "Computer Networks basics",
        "Foundational questions on TCP/IP, DNS, and routing.",
        ["networks"],
        NETWORKS,
    ),
    (
        "Database design fundamentals",
        "Indexes, transactions, normalization, query plans.",
        ["database"],
        DATABASES,
    ),
    (
        "General knowledge demo",
        "A grab-bag for the live demo recording.",
        ["general"],
        GENERAL,
    ),
]


async def _ensure_tag(session: AsyncSession, name: str, gen) -> QuizTag:
    existing = (
        await session.execute(select(QuizTag).where(QuizTag.name == name))
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    tag = QuizTag(id=gen.next_id(), name=name)
    session.add(tag)
    await session.flush()
    return tag


async def run(session: AsyncSession, owner: User) -> dict[str, QuizSet]:
    """Seed three quiz sets owned by `owner`. Idempotent on (owner_id, title)."""
    gen = get_id_generator()
    out: dict[str, QuizSet] = {}

    for title, description, tag_names, qspecs in QUIZZES:
        existing = (
            await session.execute(
                select(QuizSet).where(
                    QuizSet.owner_id == owner.id, QuizSet.title == title
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            out[title] = existing
            continue

        quiz = QuizSet(
            id=gen.next_id(),
            owner_id=owner.id,
            title=title,
            description=description,
            visibility=QuizVisibility.public,
            is_published=True,
            version=1,
        )
        session.add(quiz)
        await session.flush()

        for tag_name in tag_names:
            tag = await _ensure_tag(session, tag_name, gen)
            session.add(QuizSetTag(quiz_set_id=quiz.id, tag_id=tag.id))

        for position, (body, qtype, options, explanation) in enumerate(qspecs, start=1):
            question = Question(
                id=gen.next_id(),
                quiz_set_id=quiz.id,
                position=position,
                body=body,
                type=qtype,
                time_limit_seconds=20,
                points=1000,
                explanation=explanation,
            )
            session.add(question)
            await session.flush()
            for opt_pos, (opt_body, is_correct) in enumerate(options, start=1):
                session.add(
                    AnswerOption(
                        id=gen.next_id(),
                        question_id=question.id,
                        position=opt_pos,
                        body=opt_body,
                        is_correct=is_correct,
                    )
                )

        await session.flush()
        out[title] = quiz

    return out
