"""The task store: files under ``tasks/<status>/``, handle resolution, index allocation, gates."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

from . import lease as leases
from .repo import EXIT_REFUSED, STATUSES, TERMINAL, Repo, TaskError, warn
from .taskfile import (
    DEFAULT_CREATOR,
    DEFAULT_PRIORITY,
    DEFAULT_TYPE,
    PRIORITIES,
    SLUG_RE,
    TYPE_RANK,
    Meta,
    append_progress,
    last_progress_date,
    parse_date,
    parse_header,
    render_stub,
    split_filename,
)


@dataclass
class Task:
    path: Path
    status: str
    index: int | None
    slug: str
    meta: Meta

    @property
    def name(self) -> str:
        return self.path.name

    @property
    def handle(self) -> str:
        return f"{self.index:04d}-{self.slug}" if self.index is not None else self.slug

    def text(self) -> str:
        return self.path.read_text()

    def glob_ref(self) -> str:
        return f"tasks/*/{self.handle}.md"


def today_str() -> str:
    return date.today().isoformat()


def stale_hours() -> float:
    try:
        return float(os.environ.get("TASKS_STALE_HOURS", "24"))
    except ValueError:
        return 24.0


class Store:
    def __init__(self, repo: Repo):
        self.repo = repo

    # listing -------------------------------------------------------------------------------
    def ensure_layout(self) -> None:
        for status in STATUSES:
            self.repo.folder(status).mkdir(parents=True, exist_ok=True)

    def load(self, *, quiet: bool = False) -> list[Task]:
        tasks: list[Task] = []
        for status in STATUSES:
            folder = self.repo.folder(status)
            if not folder.is_dir():
                continue
            for p in sorted(folder.iterdir()):
                if not p.is_file() or p.suffix != ".md":
                    continue
                parsed = split_filename(p.name)
                if parsed is None:
                    if not quiet:
                        warn(f"{self.repo.rel(p)}: not NNNN-<kebab-slug>.md; ignored")
                    continue
                idx, slug = parsed
                meta = parse_header(p.read_text(), name=self.repo.rel(p))
                if not quiet:
                    for w in meta.warnings:
                        warn(w)
                tasks.append(Task(path=p, status=status, index=idx, slug=slug, meta=meta))
        tasks.sort(key=lambda t: (t.index is None, t.index or 0, t.slug))
        return tasks

    def rel(self, task: Task) -> str:
        return self.repo.rel(task.path)

    # handles -------------------------------------------------------------------------------
    @staticmethod
    def _normalise_handle(handle: str) -> tuple[int | None, str | None]:
        h = handle.strip()
        if h.startswith("tasks/"):
            h = h.rsplit("/", 1)[-1]
        if h.isdigit():
            return int(h), None
        parsed = split_filename(h if h.endswith(".md") else h + ".md")
        if parsed is None:
            return None, h
        idx, slug = parsed
        return idx, slug

    def resolve(self, handle: str, tasks: list[Task] | None = None) -> Task:
        tasks = tasks if tasks is not None else self.load(quiet=True)
        idx, slug = self._normalise_handle(handle)
        if idx is not None and slug is not None:
            hits = [t for t in tasks if t.index == idx and t.slug == slug] or [t for t in tasks if t.slug == slug]
        elif idx is not None:
            hits = [t for t in tasks if t.index == idx]
        else:
            hits = [t for t in tasks if t.slug == slug]
        if not hits:
            raise TaskError(f"unknown task {handle!r}", EXIT_REFUSED)
        if len(hits) > 1:
            raise TaskError(
                f"ambiguous handle {handle!r}: " + ", ".join(self.rel(t) for t in hits), EXIT_REFUSED
            )
        return hits[0]

    def find_slug(self, slug: str, tasks: list[Task] | None = None) -> Task | None:
        tasks = tasks if tasks is not None else self.load(quiet=True)
        hits = [t for t in tasks if t.slug == slug]
        return hits[0] if hits else None

    # allocation (caller holds the lock) ------------------------------------------------------
    def next_index(self, tasks: list[Task] | None = None) -> int:
        tasks = tasks if tasks is not None else self.load(quiet=True)
        used = [t.index for t in tasks if t.index is not None]
        return (max(used) + 1) if used else 1

    def create(self, slug: str, *, type_: str = DEFAULT_TYPE, priority: str = DEFAULT_PRIORITY,
               creator: str = DEFAULT_CREATOR, discovered_by: str | None = None,
               title: str | None = None, goal: str = "") -> Task:
        if not SLUG_RE.match(slug):
            raise TaskError(f"slug {slug!r} must be kebab-case [a-z0-9-]", EXIT_REFUSED)
        if type_ not in TYPE_RANK:
            raise TaskError(f"unknown type {type_!r}; one of {', '.join(TYPE_RANK)}", EXIT_REFUSED)
        if priority not in PRIORITIES:
            raise TaskError(f"unknown priority {priority!r}; one of {', '.join(PRIORITIES)}", EXIT_REFUSED)
        self.ensure_layout()
        tasks = self.load(quiet=True)
        if (dup := self.find_slug(slug, tasks)) is not None:
            raise TaskError(f"slug {slug!r} already exists: {self.rel(dup)}", EXIT_REFUSED)
        idx = self.next_index(tasks)
        path = self.repo.folder("todo") / f"{idx:04d}-{slug}.md"
        title = title or slug.replace("-", " ").capitalize()
        path.write_text(render_stub(title, type_=type_, priority=priority, creator=creator,
                                    discovered_by=discovered_by, goal=goal))
        self.repo.commit_paths(f"tasks: create {idx:04d}-{slug}", [path])
        return Task(path=path, status="todo", index=idx, slug=slug,
                    meta=parse_header(path.read_text()))

    def assign_indices(self) -> list[Task]:
        """Give an index to every ``<slug>.md`` that arrived without one. Caller holds the lock."""
        assigned: list[Task] = []
        tasks = self.load(quiet=True)
        nxt = self.next_index(tasks)
        for t in [t for t in tasks if t.index is None]:
            dst = t.path.with_name(f"{nxt:04d}-{t.slug}.md")
            self.repo.move(t.path, dst)
            self.repo.commit_paths(f"tasks: assign index {nxt:04d} to {t.slug}", [t.path, dst])  # both staged here
            assigned.append(Task(path=dst, status=t.status, index=nxt, slug=t.slug, meta=t.meta))
            nxt += 1
        return assigned

    # moves (caller holds the lock) ----------------------------------------------------------
    def sibling_paths(self, task: Task) -> list[Path]:
        """The task file's path in every status folder — so a crash between a rename and its commit
        (old path deleted, new path untracked) is healed by the next pathspec commit."""
        return [self.repo.folder(s) / task.name for s in STATUSES]

    def move(self, task: Task, status: str, progress_line: str, message: str) -> Task:
        dst = self.repo.folder(status) / task.name
        if dst != task.path:
            self.repo.move(task.path, dst)
        append_progress(dst, progress_line)
        self.repo.commit_paths(message, self.sibling_paths(task))
        return Task(path=dst, status=status, index=task.index, slug=task.slug, meta=task.meta)

    # gates ---------------------------------------------------------------------------------
    def gate_reason(self, task: Task, tasks: list[Task], today: date | None = None) -> str | None:
        """None = not gated. Fails open: unparseable gate -> warning + not gated."""
        today = today or date.today()
        m = task.meta
        if m.blocked_until:
            d = parse_date(m.blocked_until)
            if d is None:
                warn(f"{self.rel(task)}: blocked-until {m.blocked_until!r} is not a date; ignoring gate")
            elif d > today:
                return f"blocked-until {d.isoformat()}"
        if m.blocked_by:
            try:
                parent = self.resolve(m.blocked_by, tasks)
            except TaskError:
                warn(f"{self.rel(task)}: blocked-by {m.blocked_by!r} not found; ignoring gate")
            else:
                if parent.status not in TERMINAL:
                    return f"blocked-by {parent.handle} ({parent.status})"
        return None

    # activity ------------------------------------------------------------------------------
    def last_activity(self, task: Task, lease: leases.Lease | None) -> datetime | None:
        """Newest of: last Progress line date, file commit date, lease heartbeat."""
        candidates: list[datetime] = []
        d = last_progress_date(task.text())
        if d:
            candidates.append(datetime(d.year, d.month, d.day).astimezone())
        ts = self.repo.last_commit_timestamp(task.path)
        if ts:
            candidates.append(datetime.fromtimestamp(ts).astimezone())
        if lease and lease.heartbeat:
            candidates.append(lease.heartbeat)
        return max(candidates) if candidates else None

    def is_stale(self, task: Task, lease: leases.Lease | None, now: datetime | None = None) -> bool:
        last = self.last_activity(task, lease)
        if last is None:
            return True
        now = now or datetime.now().astimezone()
        return now - last > timedelta(hours=stale_hours())
