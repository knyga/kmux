"""``tasks`` console script. Selection is executed here, never reasoned about by the caller."""

from __future__ import annotations

import argparse
import json
import sys

from . import loopstate
from .claim import claim, heartbeat
from .close import close
from .lock import ClaimLock
from .ops import outcomes, park, resume_briefing, status_rows
from .repo import EXIT_OK, Repo, TaskError
from .store import Store
from .taskfile import DEFAULT_CREATOR, DEFAULT_PRIORITY, DEFAULT_TYPE, PRIORITIES, TYPES


def _p(obj) -> None:
    print(json.dumps(obj, indent=2, sort_keys=True))


def cmd_index(repo: Repo, a: argparse.Namespace) -> int:
    store = Store(repo)
    if a.create:
        with ClaimLock(repo):
            t = store.create(a.create, type_=a.type, priority=a.priority, creator=a.creator,
                             discovered_by=a.discovered_by, title=a.title)
        print(f"created {store.rel(t)}")
        return EXIT_OK
    if a.assign:
        with ClaimLock(repo):
            done = store.assign_indices()
        for t in done:
            print(f"assigned {store.rel(t)}")
        if not done:
            print("nothing to assign")
        return EXIT_OK
    tasks = store.load()
    if not tasks:
        print("(no tasks)")
    for t in tasks:
        idx = f"{t.index:04d}" if t.index is not None else "----"
        m = t.meta
        print(f"{idx}  {t.status:<22} {t.slug:<40} {m.type}/{m.priority}/{m.creator}  {m.title}")
    return EXIT_OK


def cmd_claim(repo: Repo, a: argparse.Namespace) -> int:
    if a.heartbeat:
        lease = heartbeat(repo)
        print(f"heartbeat {lease.slug} session {lease.session} pid {lease.pid} at {lease.heartbeatAt}")
        return EXIT_OK
    res = claim(repo, slug=a.slug)
    if res.code != EXIT_OK:
        print(json.dumps({"claimed": False, "reason": res.message}) if a.json else res.message)
        return res.code
    if a.json:
        _p(res.payload)
    else:
        p = res.payload
        m = p["meta"]
        print(f"claimed {p['index']:04d}-{p['slug']} (mode={p['mode']}) — {m['type']}/{m['priority']}/{m['creator']} — {m['title']}")
        print(f"  file      {p['file']}")
        print(f"  branch    {p['branch']}")
        print(f"  worktree  {p['worktree']}")
        print(f"  session   {p['session']}   (export TASKS_SESSION={p['session']} for heartbeats)")
    return EXIT_OK


def cmd_status(repo: Repo, a: argparse.Namespace) -> int:
    rows = status_rows(repo, stale_only=a.stale)
    if not rows:
        print("(no adoptable tasks)" if a.stale else "(no leases)")
    for r in rows:
        print(r.line())
    return EXIT_OK


def cmd_resume(repo: Repo, a: argparse.Namespace) -> int:
    print(resume_briefing(repo, a.handle))
    return EXIT_OK


def cmd_park(repo: Repo, a: argparse.Namespace) -> int:
    t = park(repo, a.handle, a.reason)
    print(f"parked {Store(repo).rel(t)}")
    return EXIT_OK


def cmd_close(repo: Repo, a: argparse.Namespace) -> int:
    res = close(repo, a.handle, cancel=a.cancel, dry_run=a.dry_run, no_merge=a.no_merge,
                force_worktree=a.force_worktree)
    print(res.summary())
    return EXIT_OK


def cmd_outcomes(repo: Repo, a: argparse.Namespace) -> int:
    hits = outcomes(repo, a.keyword)
    if not hits:
        print(f"no closed task has {a.keyword!r} in its ## Outcome")
    for path, body in hits:
        print(f"== {path}\n{body}\n")
    return EXIT_OK


def cmd_loop_state(repo: Repo, a: argparse.Namespace) -> int:
    if a.action == "begin":
        _p(loopstate.begin(repo, a.slug))
    elif a.action == "record":
        _p(loopstate.record(repo, a.slug, a.status, a.note))
    elif a.action == "report":
        _p(loopstate.report(repo))
    elif a.action == "session":
        print(loopstate.session(repo))
    elif a.action == "reset":
        loopstate.reset(repo)
        print("loop state reset")
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="tasks", description="Task tracker: markdown files under tasks/, folder = status.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("index", help="list tasks, --create a stub, or --assign missing indices")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--create", metavar="SLUG")
    g.add_argument("--assign", action="store_true")
    p.add_argument("--type", default=DEFAULT_TYPE, choices=TYPES)
    p.add_argument("--priority", default=DEFAULT_PRIORITY, choices=PRIORITIES)
    p.add_argument("--creator", default=DEFAULT_CREATOR)
    p.add_argument("--discovered-by", metavar="SLUG")
    p.add_argument("--title")
    p.set_defaults(fn=cmd_index)

    p = sub.add_parser("claim", help="claim the next task (exit 0 claimed, 3 nothing, 4 refused)")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--slug", metavar="HANDLE", help="claim exactly this task")
    g.add_argument("--heartbeat", action="store_true", help="refresh this session's lease")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_claim)

    p = sub.add_parser("status", help="leases with live/dead verdict; --stale = adoptable only")
    p.add_argument("--stale", action="store_true")
    p.set_defaults(fn=cmd_status)

    p = sub.add_parser("resume", help="briefing for work this machine dropped")
    p.add_argument("handle", nargs="?")
    p.set_defaults(fn=cmd_resume)

    p = sub.add_parser("park", help="move to human_action_required/")
    p.add_argument("handle")
    p.add_argument("--reason", required=True, help="what a human must do")
    p.set_defaults(fn=cmd_park)

    p = sub.add_parser("close", help="gates -> merge -> done/ (exit 2 refused, nothing moved)")
    p.add_argument("handle")
    p.add_argument("--cancel", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--no-merge", action="store_true")
    p.add_argument("--force-worktree", action="store_true",
                   help="discard uncommitted changes in the task worktree on retire (default: refuse)")
    p.set_defaults(fn=cmd_close)

    p = sub.add_parser("outcomes", help="grep ## Outcome of done/ + cancelled/")
    p.add_argument("keyword")
    p.set_defaults(fn=cmd_outcomes)

    p = sub.add_parser("loop-state", help="solve-loop bookkeeping (.solve-loop/state.json)")
    ls = p.add_subparsers(dest="action", required=True)
    q = ls.add_parser("begin")
    q.add_argument("slug")
    q = ls.add_parser("record")
    q.add_argument("slug")
    q.add_argument("status", choices=loopstate.STATUSES)
    q.add_argument("note")
    ls.add_parser("report")
    ls.add_parser("session", help="print (creating once) the run's TASKS_SESSION id")
    ls.add_parser("reset")
    p.set_defaults(fn=cmd_loop_state)
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        repo = Repo.discover()
        return args.fn(repo, args)
    except TaskError as e:
        print(f"tasks: {e}", file=sys.stderr)
        return e.code
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
