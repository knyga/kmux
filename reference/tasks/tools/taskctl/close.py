"""``tasks close`` — one locked sequence that stops at the first refusal without moving anything.

1. cheap gates (all reported at once)            [lock held]
2. expensive gate in a throwaway worktree        [NO lock]      skipped by --cancel / --no-merge
3. re-validate cheap gates, land, move, retire   [lock held]
"""

from __future__ import annotations

import os
import shlex
import subprocess
from dataclasses import dataclass, field

from . import lease as leases
from .claim import current_session, is_mine
from .lock import ClaimLock
from .repo import EXIT_REFUSED, EXIT_REFUSED_GATE, Repo, TaskError
from .store import Store, Task, today_str
from .taskfile import followup_problems, has_verdict, unchecked_items

GATE_FILE = "tasks/gate.cmds"


@dataclass
class CloseResult:
    task: Task
    actions: list[str] = field(default_factory=list)
    dry_run: bool = False

    def summary(self) -> str:
        head = "would:" if self.dry_run else "done:"
        return "\n".join([head] + [f"  - {a}" for a in self.actions])


def resolve_gate_cmds(gate_cmds: list[list[str]] | None, repo: Repo | None = None) -> list[list[str]]:
    """Explicit argument > env ``TASKS_GATE_CMDS`` (``;;``-separated) > ``tasks/gate.cmds`` in the main
    checkout (one command per line, ``#`` comments). Read from the main checkout, never the branch, so a
    task cannot relax the gate that judges it. No commands = no expensive gate (close says so)."""
    if gate_cmds is not None:
        return gate_cmds
    env = os.environ.get("TASKS_GATE_CMDS")
    if env is not None:
        return [shlex.split(part) for part in env.split(";;") if part.strip()]
    if repo is not None and (path := repo.root / GATE_FILE).is_file():
        lines = (ln.strip() for ln in path.read_text().splitlines())
        return [shlex.split(ln) for ln in lines if ln and not ln.startswith("#")]
    return []


def cheap_gate_problems(task: Task, repo: Repo | None = None, *, cancel: bool = False,
                        no_merge: bool = False, force_worktree: bool = False) -> list[str]:
    """All cheap refusals at once. ``--cancel`` needs only the Verdict line; items and followups gate
    ``done`` only; the landing preconditions are checked here so nothing expensive runs for a refusal
    knowable up front."""
    text = task.text()
    problems: list[str] = []
    if not has_verdict(text):
        problems.append("## Outcome has no line matching 'Verdict:' (mandatory, also for --cancel)")
    if not cancel:
        problems += [f"unchecked item: {ln}" for ln in unchecked_items(text)]
        problems += [f"unresolved followup: {ln}" for ln in followup_problems(text)]
    if repo is not None:
        will_land = not cancel and not no_merge and _commits_ahead(repo, task.slug) > 0
        if will_land and (staged := repo.staged_paths()):
            problems.append("main checkout has staged changes (index != HEAD), which would block the merge; "
                            "unstage them first: git restore --staged -- " + " ".join(staged))
        if will_land and (current := repo.current_branch()) != repo.main_branch:
            problems.append(f"main checkout is on {current!r}, not {repo.main_branch!r}; check out "
                            f"{repo.main_branch} (or use --no-merge)")
        wt = repo.worktree_paths().get(task.slug)
        if wt is not None and wt.is_dir() and not force_worktree:
            dirty = repo.git("status", "--short", cwd=wt, check=False).stdout.rstrip()
            if dirty:
                problems.append(f"worktree {repo.rel(wt)} has uncommitted changes; commit or discard them "
                                f"(or pass --force-worktree to discard on retire):\n{dirty}")
    return problems


def _refuse(problems: list[str], task: Task, store: Store) -> TaskError:
    body = "\n".join(f"  - {p}" for p in problems)
    return TaskError(f"refused to close {store.rel(task)}; nothing moved:\n{body}", EXIT_REFUSED_GATE)


def _commits_ahead(repo: Repo, branch: str) -> int:
    if not repo.branch_exists(branch):
        return 0
    out = repo.git_out("rev-list", "--count", f"{repo.main_branch}..{branch}")
    return int(out or 0)


def _tail(text: str, n: int = 30) -> str:
    lines = text.rstrip().splitlines()
    return "\n".join(lines[-n:])


def run_expensive_gate(repo: Repo, slug: str, cmds: list[list[str]]) -> list[str]:
    """Merge main+branch in a throwaway worktree and run the gate commands there. Returns problems."""
    repo.worktrees_dir.mkdir(parents=True, exist_ok=True)
    gate_wt = repo.worktrees_dir / f"_gate-{slug}-{os.getpid()}"
    repo.git("worktree", "add", "--detach", "--", str(gate_wt), repo.main_branch)
    problems: list[str] = []
    try:
        merge = repo.git("merge", "--no-commit", "--no-ff", slug, cwd=gate_wt, check=False)
        if merge.returncode != 0:
            return [f"merge of {slug} into {repo.main_branch} does not complete cleanly:\n{_tail(merge.stdout + merge.stderr)}"]
        env = dict(os.environ)
        if (gate_wt / "src").is_dir():
            env["PYTHONPATH"] = str(gate_wt / "src") + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
        for cmd in cmds:
            argv = list(cmd)
            # A relative tool path the fresh worktree lacks (ignored .venv/, node_modules/) runs from main.
            if argv and "/" in argv[0] and not os.path.isabs(argv[0]) and not (gate_wt / argv[0]).exists() \
                    and (repo.root / argv[0]).exists():
                argv[0] = str(repo.root / argv[0])
            proc = subprocess.run(argv, cwd=str(gate_wt), text=True, capture_output=True, env=env)
            if proc.returncode != 0:
                problems.append(f"gate failed ({proc.returncode}): {' '.join(cmd)}\n{_tail(proc.stdout + proc.stderr)}")
                break
    finally:
        repo.git("worktree", "remove", "--force", "--", str(gate_wt), check=False)
    return problems


def _land(repo: Repo, task: Task, store: Store) -> str:
    current = repo.current_branch()
    if current != repo.main_branch:
        raise TaskError(
            f"refused: main checkout is on {current!r}, not {repo.main_branch!r}; check out "
            f"{repo.main_branch} (or use --no-merge). Nothing moved.", EXIT_REFUSED_GATE)
    msg = f"Merge branch '{task.slug}' (task {task.handle})"
    merge = repo.git("merge", "--no-ff", "--no-edit", "-m", msg, task.slug, check=False)
    if merge.returncode != 0:
        repo.git("merge", "--abort", check=False)
        raise TaskError(
            f"refused: git merge --no-ff {task.slug} did not complete cleanly; merge aborted, nothing moved:\n"
            f"{_tail(merge.stdout + merge.stderr)}", EXIT_REFUSED_GATE)
    return repo.git_out("rev-parse", "--short", "HEAD")


def _retire(repo: Repo, task: Task, *, cancel: bool, merged: bool, force_worktree: bool,
            actions: list[str]) -> None:
    registered = repo.worktree_paths()
    wt = registered.get(task.slug)
    worktree_kept = False
    if wt is not None:
        args = ["worktree", "remove", *(["--force"] if force_worktree else []), "--", str(wt)]
        res = repo.git(*args, check=False)
        if res.returncode == 0:
            actions.append(f"removed worktree {repo.rel(wt)}" + (" (--force)" if force_worktree else ""))
        else:
            worktree_kept = True
            dirty = repo.git("status", "--short", cwd=wt, check=False).stdout.rstrip()
            actions.append(f"KEPT worktree {repo.rel(wt)} — git worktree remove failed; it holds:\n{dirty}\n"
                           f"    finish with: git worktree remove --force {repo.rel(wt)} && git branch -d {task.slug}")
    if repo.branch_exists(task.slug):
        if worktree_kept:
            actions.append(f"kept branch {task.slug}: its worktree is still registered"
                           + (" (the merge itself landed)" if merged else ""))
        elif cancel:
            repo.git("branch", "-D", task.slug, check=False)
            actions.append(f"deleted branch {task.slug} (-D)")
        elif merged or _commits_ahead(repo, task.slug) == 0:
            res = repo.git("branch", "-d", task.slug, check=False)
            actions.append(f"deleted branch {task.slug}" if res.returncode == 0
                           else f"kept branch {task.slug}: git branch -d refused ({res.stderr.strip()})")
        else:
            actions.append(f"kept branch {task.slug} (not merged)")
    leases.drop(repo, task.slug)
    actions.append("dropped lease")


def _retire_leftovers(repo: Repo, task: Task, store: Store, *, cancel: bool, dry_run: bool,
                      force_worktree: bool) -> CloseResult:
    """A crash between the move-commit and retire leaves branch/worktree/lease behind; closing a task
    that is already done/cancelled retires only those (and is a no-op otherwise)."""
    leftovers = repo.branch_exists(task.slug) or task.slug in repo.worktree_paths() or leases.load(repo, task.slug)
    if not leftovers:
        raise TaskError(f"{store.rel(task)} is already {task.status}", EXIT_REFUSED)
    actions = [f"{store.rel(task)} is already {task.status}; retiring leftovers only"]
    if dry_run:
        actions.append(f"retire worktree + branch {task.slug}, drop lease")
        return CloseResult(task, actions, dry_run=True)
    _retire(repo, task, cancel=cancel or task.status == "cancelled", merged=False, force_worktree=force_worktree,
            actions=actions)
    return CloseResult(task, actions)


def close(repo: Repo, handle: str, *, cancel: bool = False, dry_run: bool = False, no_merge: bool = False,
          force_worktree: bool = False, gate_cmds: list[list[str]] | None = None) -> CloseResult:
    store = Store(repo)
    # 1. cheap gates, under the lock
    with ClaimLock(repo):
        task = store.resolve(handle)
        if task.status in ("done", "cancelled"):
            return _retire_leftovers(repo, task, store, cancel=cancel, dry_run=dry_run, force_worktree=force_worktree)
        lease = leases.load(repo, task.slug)
        if lease is not None and lease.is_live() and not is_mine(lease, current_session()):
            raise TaskError(f"refused: {task.handle} is held by live session {lease.session} "
                            f"(pid {lease.pid} on {lease.host})", EXIT_REFUSED)
        problems = cheap_gate_problems(task, repo, cancel=cancel, no_merge=no_merge, force_worktree=force_worktree)
        if problems:
            raise _refuse(problems, task, store)
        ahead = _commits_ahead(repo, task.slug)
        gated_tip = repo.git_out("rev-parse", task.slug) if ahead else None
    # 2. expensive gate, NO lock held
    run_gate = not cancel and not no_merge and ahead > 0
    actions: list[str] = []
    if run_gate and not (cmds := resolve_gate_cmds(gate_cmds, repo)):
        actions.append(f"WARNING: no gate commands ({GATE_FILE} absent or empty, TASKS_GATE_CMDS unset); "
                       "the merged tree was NOT verified")
    elif run_gate:
        problems = run_expensive_gate(repo, task.slug, cmds)
        if problems:
            raise _refuse(problems, task, store)
        actions.append(f"expensive gate passed on merged tree ({ahead} commit(s) on {task.slug})")
    elif ahead == 0 and not cancel:
        actions.append(f"no commits on branch {task.slug} beyond {repo.main_branch}; nothing to merge")
    # 3. re-take the lock, re-validate, land, move, retire
    with ClaimLock(repo):
        task = store.resolve(task.handle)
        if task.status in ("done", "cancelled"):
            raise TaskError(f"{store.rel(task)} became {task.status} meanwhile", EXIT_REFUSED)
        problems = cheap_gate_problems(task, repo, cancel=cancel, no_merge=no_merge, force_worktree=force_worktree)
        if run_gate and repo.git_out("rev-parse", task.slug) != gated_tip:
            problems.append(f"branch {task.slug} moved after the expensive gate ran; re-run close")
        if problems:
            raise _refuse(problems, task, store)
        target = "cancelled" if cancel else "done"
        will_merge = not cancel and not no_merge and _commits_ahead(repo, task.slug) > 0
        if dry_run:
            if will_merge:
                actions.append(f"merge --no-ff {task.slug} into {repo.main_branch} (checkout is on {repo.current_branch()!r})")
            actions.append(f"move {store.rel(task)} -> tasks/{target}/{task.name} and commit")
            actions.append(f"retire worktree + branch {task.slug}, drop lease")
            return CloseResult(task, actions, dry_run=True)
        merged_sha = None
        if will_merge:
            merged_sha = _land(repo, task, store)
            actions.append(f"merged {task.slug} into {repo.main_branch} as {merged_sha}")
        if cancel:
            note = "cancelled"
        elif merged_sha:
            note = f"closed: merged as {merged_sha}"
        else:
            note = "closed (not merged)"
        task = store.move(task, target, f"- {today_str()} {note}", f"tasks: {target} {task.handle}")
        actions.append(f"moved to {store.rel(task)}")
        _retire(repo, task, cancel=cancel, merged=merged_sha is not None, force_worktree=force_worktree,
                actions=actions)
    return CloseResult(task, actions)
