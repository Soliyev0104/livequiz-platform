"""Canonical Redis key formatters (room:{code}:*, match:{id}:*) — filled in P05.

P04 lands the quiz-cache key builders here: list cache (with viewer
identity baked into the hash so anonymous and authenticated views do
not cross-leak) and a per-quiz detail key reserved for P05.
"""

from __future__ import annotations

import hashlib
import json

QUIZ_LIST_PREFIX = "cache:quiz:list:"


def quiz_list_cache_key(
    *,
    viewer_id: int | None,
    q: str | None,
    owner_id: int | None,
    tag: str | None,
    limit: int,
    offset: int,
) -> str:
    """SHA1 of the filter payload, prefixed with ``cache:quiz:list:``.

    ``viewer_id`` MUST be part of the hashed input — anonymous and
    authenticated owners see different rows. Without it, an owner's
    drafts could leak across sessions, or be hidden by an anonymous
    cached payload.
    """
    payload = {
        "viewer": str(viewer_id) if viewer_id else "anon",
        "q": q or "",
        "owner_id": str(owner_id) if owner_id else "",
        "tag": tag or "",
        "limit": int(limit),
        "offset": int(offset),
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return f"{QUIZ_LIST_PREFIX}{hashlib.sha1(blob).hexdigest()}"


def quiz_detail_cache_key(quiz_id: int, version: int) -> str:
    """Per-quiz cache key. Reserved for P05; defined here so both phases
    agree on the key format. P04 only uses the list cache."""
    return f"cache:quiz:{quiz_id}:v{version}"
