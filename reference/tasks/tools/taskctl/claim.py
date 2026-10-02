"""``tasks claim`` — selection and mutation together, in one process, under the one mutex."""

from __future__ import annotations

import os
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path

from . import lease as leases
from .lock import ClaimLock
from .order import sort_key
from .procs import hostname, proc_start, session_pid
from .repo import EXIT_NOTHING, EXIT_OK, EXIT_REFUSED, Repo, TaskError
from .store import Store, Task, today_str
from .taskfile import last_claim_host


@dataclass
class ClaimResult:
    code: int
    payload: dict
    message: str = ""


def current_session() -> str:
    return os.environ.get("TASKS_SESSION") or uuid.uuid4().hex


def ensure_branch_and_worktree(repo: Repo, slug: str) -> tuple[str, str]:
    """Branch ``<slug>`` (from main, or reused) + worktree ``.worktrees/<slug>`` (reused if present)."""
    repo.worktrees_dir.mkdir(parents=True, exist_ok=True)
    wt = repo.worktrees_dir / slug
    registered = repo.worktree_paths()
    existing = registered.get(slug)
    if existing is not None and existing.resolve() == wt.resolve() and wt.is_dir():
        return slug, str(wt)
    if existing is not None and existing.resolve() == repo.root.resolve():
        raise TaskError(f"branch {slug!r} is checked out in the main checkout ({repo.rel(existing) or '.'}); "
                        f"switch it to {repo.main_branch!r} first", EXIT_REFUSED)
    if existing is not None and existing.is_dir():
        return slug, str(existing)  # branch checked out in another worktree; honour it
    repo.git("worktree", "prune")
    if wt.exists() and not any(wt.iterdir()):
        wt.rmdir()
    if wt.exists():
        raise TaskError(f"{repo.rel(wt)} exists but is not a registered worktree; move it away first",
                        EXIT_REFUSED)
    if repo.branch_exists(slug):
        repo.git("worktree", "add", "--", str(wt), slug)
    else:
        repo.git("worktree", "add", "-b", slug, "--", str(wt), repo.main_branch)
    return slug, str(wt)


def is_mine(lease: leases.Lease, session: str) -> bool:
    """This session's lease. A caller that names its own session (TASKS_SESSION set) must match the
    lease's session id exactly; only an anonymous caller falls back to "same long-lived process on this
    host", so two parallel subagents under one coordinator never take each other's tasks."""
    if lease.session == session:
        return True
    if os.environ.get("TASKS_SESSION"):
        return False
    return lease.host == hostname() and lease.pid == session_pid()


def _fast_forward_fresh_branch(repo: Repo, slug: str, worktree: str) -> None:
    """A branch with no commits of its own is moved to the main checkout's new tip, so the worktree holds
    ``tasks/in_progress/NNNN-<slug>.md`` with the claim line (the path the claim JSON hands over)."""
    if int(repo.git_out("rev-list", "--count", f"{repo.main_branch}..{slug}") or 0) > 0:
        return  # the solver's own commits live here; never rewrite them
    tip = repo.git_out("rev-parse", "HEAD")
    repo.git("merge", "--ff-only", "-q", tip, cwd=Path(worktree), check=False)


def _pools(store: Store, tasks: list[Task], all_leases: dict[str, leases.Lease],
           session: str) -> list[tuple[str, list[Task]]]:
    """RESUME (this host's interrupted or still-held work) > ADOPT (stale + unleased) > todo > stale parked."""
    host = hostname()
    resume, adopt, todo, parked = [], [], [], []
    for t in tasks:
        lease = all_leases.get(t.slug)
        unleased = lease is None or not lease.is_live()
        if t.status == "in_progress":
            if lease is not None and lease.host == host and not lease.is_live():
                resume.append(t)  # session pid dead on this host: evidence of a dropped session
            elif lease is not None and lease.is_live() and is_mine(lease, session):
                resume.append(t)  # still ours (e.g. a stalled subagent); the next claim re-enters it
            elif lease is None and last_claim_host(t.text()) == host:
                resume.append(t)  # claim interrupted before its lease was written
            elif unleased and store.is_stale(t, lease):
                adopt.append(t)
        elif t.status == "todo":
            todo.append(t)
        elif t.status == "human_action_required":
            if unleased and store.is_stale(t, lease):
                parked.append(t)
    return [("resume", resume), ("adopt", adopt), ("new", todo), ("adopt", parked)]


def _candidates(store: Store, tasks: list[Task], all_leases: dict[str, leases.Lease], session: str):
    """Yield (mode, task, branch, worktree) for every candidate that is not gated AND whose branch +
    worktree can be prepared, in pool/rank order. Candidates whose worktree cannot be set up are skipped
    (printed like a gated skip) so they never wedge the queue."""
    repo = store.repo
    for mode, pool in _pools(store, tasks, all_leases, session):
        ranked = sorted(pool, key=lambda t: sort_key(t.meta, repo.added_timestamp(t.path)))
        for t in ranked:
            if mode != "resume":
                reason = store.gate_reason(t, tasks)
                if reason:
                    print(f"skipped (gated): {store.rel(t)} — {reason}", file=sys.stderr)
                    continue
            try:
                branch, worktree = ensure_branch_and_worktree(repo, t.slug)
            except TaskError as e:
                print(f"skipped (worktree): {store.rel(t)} — {e}", file=sys.stderr)
                continue
            yield mode, t, branch, worktree


def _record_claim(store: Store, task: Task, mode: str, session: str) -> Task:
    """Move + claim line + commit. On failure (hook, gpg, disk) the file is put back at its previous path
    with its previous content and the index is reset, so nothing half-claimed is left behind."""
    repo = store.repo
    line = f"- {today_str()} claimed by {session} on host={hostname()} (mode={mode})"
    try:
        return store.move(task, "in_progress", line, f"tasks: claim {task.handle} (mode={mode})")
    except TaskError:
        dst = repo.folder("in_progress") / task.name
        if dst != task.path and dst.exists():
            os.replace(dst, task.path)
        repo.git("reset", "-q", "--", *[repo.rel(p) for p in store.sibling_paths(task)], check=False)
        if repo.in_index(repo.rel(task.path)):
            repo.git("checkout", "-q", "--", repo.rel(task.path), check=False)
        raise


def claim(repo: Repo, *, slug: str | None = None, session: str | None = None) -> ClaimResult:
    store = Store(repo)
    session = session or current_session()
    with ClaimLock(repo):
        tasks = store.load()
        all_leases = leases.load_all(repo)
        if slug:
            task = store.resolve(slug, tasks)
            if task.status in ("done", "cancelled"):
                raise TaskError(f"{store.rel(task)} is already {task.status}", EXIT_REFUSED)
            lease = all_leases.get(task.slug)
            if lease and lease.is_live() and not is_mine(lease, session):
                raise TaskError(
                    f"refused: {task.handle} is held by live session {lease.session} "
                    f"(pid {lease.pid} on {lease.host})", EXIT_REFUSED)
            mode = "slug"
            branch, worktree = ensure_branch_and_worktree(repo, task.slug)  # refusal here = exit 4, nothing moved
            task = _record_claim(store, task, mode, session)
        else:
            task = None
            for cand_mode, cand, cand_branch, cand_worktree in _candidates(store, tasks, all_leases, session):
                try:
                    task = _record_claim(store, cand, cand_mode, session)
                except TaskError as e:
                    print(f"skipped (commit): {store.rel(cand)} — {e}", file=sys.stderr)
                    continue
                mode, branch, worktree = cand_mode, cand_branch, cand_worktree
                break
            if task is None:
                return ClaimResult(EXIT_NOTHING, {}, "nothing available")
        _fast_forward_fresh_branch(repo, task.slug, worktree)
        pid = session_pid()
        leases.write(repo, leases.Lease(slug=task.slug, session=session, pid=pid, host=hostname(),
                                        branch=branch, worktree=worktree, heartbeatAt=leases.iso(leases.now_utc()),
                                        pidStart=proc_start(pid)))
    payload = {"slug": task.slug, "index": task.index, "branch": branch, "worktree": worktree, "mode": mode,
               "meta": task.meta.as_dict(), "file": store.rel(task), "session": session}
    return ClaimResult(EXIT_OK, payload)


def heartbeat(repo: Repo, session: str | None = None) -> leases.Lease:
    """Refresh this session's lease (under the mutex, so a concurrent claim cannot judge it dead while
    it is being revived): found via TASKS_SESSION, else by this host's session pid."""
    session = session or os.environ.get("TASKS_SESSION") or ""
    with ClaimLock(repo):
        all_leases = leases.load_all(repo)
        hits = [lease for lease in all_leases.values() if is_mine(lease, session)]
        if not hits:
            raise TaskError("no lease for this session (set TASKS_SESSION to the claim's session id)", EXIT_REFUSED)
        if len(hits) > 1:
            raise TaskError("this session holds several leases: " + ", ".join(lease.slug for lease in hits),
                            EXIT_REFUSED)
        lease = hits[0]
        lease.heartbeatAt = leases.iso(leases.now_utc())
        lease.pid = session_pid()
        lease.pidStart = proc_start(lease.pid)
        lease.host = hostname()
        leases.write(repo, lease)
    return lease
