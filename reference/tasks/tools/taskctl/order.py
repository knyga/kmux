"""Ranking within a claim pool: priority -> type -> creator -> age. Pool precedence is decided by
the caller and is absolute; this module never mixes pools."""

from __future__ import annotations

from .taskfile import DEFAULT_PRIORITY, DEFAULT_TYPE, PRIORITIES, TYPE_RANK, Meta


def priority_rank(priority: str) -> int:
    return PRIORITIES.index(priority) if priority in PRIORITIES else PRIORITIES.index(DEFAULT_PRIORITY)


def type_rank(type_: str) -> int:
    return TYPE_RANK.get(type_, TYPE_RANK[DEFAULT_TYPE])


def creator_rank(creator: str) -> tuple[int, str]:
    return (0, "") if creator == "user" else (1, creator)


def sort_key(meta: Meta, added_ts: float) -> tuple:
    """Smaller sorts first. ``added_ts`` = unix time the file was added (older first)."""
    return (priority_rank(meta.priority), type_rank(meta.type), creator_rank(meta.creator), added_ts)
