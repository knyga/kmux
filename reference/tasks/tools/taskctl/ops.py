"""status / resume / park / outcomes."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from . import lease as leases
from .claim import is_mine
from .lock import ClaimLock
from .procs import hostname
from .repo import EXIT_REFUSED, Repo, TaskError
from .store import Store, Task, today_str
from .taskfile import last_next_line, progress_lines, sections, unchecked_items


def _fmt_age(td) -> str:
    if td is None:
        return "?"
    secs = int(td.total_seconds())
    if secs < 3600:
        return f"{secs // 60}m"
    if secs < 86400:
        return f"{secs // 3600}h{(secs % 3600) // 60:02d}m"
    return f"{secs // 86400}d{(secs % 86400) // 3600}h"


@dataclass
class StatusRow:
    slug: str
    status: str
    verdict: str
    age: str
    session: str
    pid: int
    host: str
    adoptable: bool

    def line(self) -> str:
        flag = "  adoptable" if self.adoptable else ""
        return f"{self.slug:<40} {self.status:<22} {self.verdict:<8} hb {self.age:>7}  pid {self.pid} @{self.host} session {self.session}{flag}"


def status_rows(repo: Repo, *, stale_only: bool = False) -> list[StatusRow]:
    store = Store(repo)
    tasks = store.load(quiet=True)
    by_slug = {t.slug: t for t in tasks}
    all_leases = leases.load_all(repo)
    rows: list[StatusRow] = []
    seen = set()
    for slug, lease in sorted(all_leases.items()):
        t = by_slug.get(slug)
        status = t.status if t else "missing"
        live = lease.is_live()
        adoptable = bool(t) and status == "in_progress" and not live and (
            lease.host == hostname() or store.is_stale(t, lease))
        rows.append(StatusRow(slug, status, lease.verdict(), _fmt_age(lease.age()), lease.session, lease.pid,
                              lease.host, adoptable))
        seen.add(slug)
    for t in tasks:
        if t.status == "in_progress" and t.slug not in seen:
            rows.append(StatusRow(t.slug, t.status, "no-lease", "-", "-", 0, "-", store.is_stale(t, None)))
    if stale_only:
        rows = [r for r in rows if r.adoptable]
    return rows


def _default_resume_task(repo: Repo, store: Store, tasks: list[Task]) -> Task:
    all_leases = leases.load_all(repo)
    dead_here = [lease for lease in all_leases.values() if lease.host == hostname() and not lease.is_live()]
    if dead_here:
        dead_here.sort(key=lambda lease: lease.heartbeatAt, reverse=True)
        return store.resolve(dead_here[0].slug, tasks)
    session = os.environ.get("TASKS_SESSION") or ""
    mine = [lease for lease in all_leases.values() if is_mine(lease, session)]
    if mine:
        return store.resolve(mine[0].slug, tasks)
    raise TaskError("nothing to resume: no dead lease on this host and no lease for this session", EXIT_REFUSED)


def resume_briefing(repo: Repo, handle: str | None) -> str:
    store = Store(repo)
    tasks = store.load(quiet=True)
    task = store.resolve(handle, tasks) if handle else _default_resume_task(repo, store, tasks)
    text = task.text()
    lease = leases.load(repo, task.slug)
    out = [f"# resume {task.handle} [{task.status}] — {task.meta.title}", f"file: {store.rel(task)}"]
    if lease:
        out.append(f"lease: {lease.verdict()} session {lease.session} pid {lease.pid} @{lease.host} hb {lease.heartbeatAt}")
    out += ["", "## Progress"] + (progress_lines(text) or ["(none)"])
    nxt = last_next_line(text)
    out += ["", f"NEXT: {nxt.split('NEXT:', 1)[1].strip()}" if nxt else "NEXT: (no NEXT: line recorded)"]
    branch = task.slug
    out += ["", f"## git log --oneline {repo.main_branch}..{branch}"]
    if repo.branch_exists(branch):
        log = repo.git_out("log", "--oneline", f"{repo.main_branch}..{branch}")
        out += log.splitlines() or ["(no commits beyond main)"]
    else:
        out.append("(no branch)")
    wt = Path(lease.worktree) if lease and lease.worktree else repo.worktrees_dir / task.slug
    out += ["", f"## git status --short ({repo.rel(wt)})"]
    if wt.is_dir():
        st = repo.git("status", "--short", cwd=wt, check=False).stdout.rstrip()
        out += st.splitlines() or ["(clean)"]
    else:
        out.append("(worktree missing)")
    out += ["", "## Unchecked items"] + (unchecked_items(text) or ["(none)"])
    return "\n".join(out)


def park(repo: Repo, handle: str, reason: str) -> Task:
    if not reason.strip():
        raise TaskError("--reason must say what a human must do", EXIT_REFUSED)
    store = Store(repo)
    with ClaimLock(repo):
        task = store.resolve(handle)
        if task.status in ("done", "cancelled"):
            raise TaskError(f"{store.rel(task)} is already {task.status}", EXIT_REFUSED)
        lease = leases.load(repo, task.slug)
        if lease is not None and lease.is_live() and not is_mine(lease, os.environ.get("TASKS_SESSION") or ""):
            raise TaskError(f"refused: {task.handle} is held by live session {lease.session} "
                            f"(pid {lease.pid} on {lease.host})", EXIT_REFUSED)
        task = store.move(task, "human_action_required", f"- {today_str()} parked: {reason.strip()}",
                          f"tasks: park {task.handle}")
        leases.drop(repo, task.slug)
    return task


def outcomes(repo: Repo, keyword: str) -> list[tuple[str, str]]:
    store = Store(repo)
    kw = keyword.lower()
    hits = []
    for t in store.load(quiet=True):
        if t.status not in ("done", "cancelled"):
            continue
        body = sections(t.text()).get("Outcome")
        if body and kw in body.lower():
            hits.append((store.rel(t), body.strip()))
    return hits
