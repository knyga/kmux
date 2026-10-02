"""Index allocation under concurrency, handle resolution, --assign."""

import subprocess
from concurrent.futures import ThreadPoolExecutor

from _helpers import create, git, run_tasks

from taskctl.repo import TaskError
from taskctl.store import Store


def test_concurrent_create_yields_unique_indices(repo):
    slugs = [f"task-{i}" for i in range(8)]
    with ThreadPoolExecutor(max_workers=8) as pool:
        procs = list(pool.map(lambda s: run_tasks(repo, "index", "--create", s), slugs))
    assert all(p.returncode == 0 for p in procs), [p.stderr for p in procs if p.returncode]
    files = sorted(p.name for p in (repo.root / "tasks" / "todo").glob("*.md"))
    indices = [int(f[:4]) for f in files]
    assert len(indices) == 8
    assert len(set(indices)) == 8, indices  # gaps would be legal; duplicates are not
    assert not (repo.root / "tasks" / ".claim.lock").exists()
    # every create is its own commit touching only its own file
    log = git(repo.root, "log", "--format=%s", "--name-only", "--diff-filter=A", "-8")
    commits = [blk.strip().splitlines() for blk in log.split("tasks: create ") if blk.strip()]
    assert len(commits) == 8
    for blk in commits:
        slug, paths = blk[0], [ln for ln in blk[1:] if ln]
        assert paths == [f"tasks/todo/{slug}.md"], blk
    assert git(repo.root, "status", "--short") == ""


def test_duplicate_slug_refused(repo):
    create(repo, "same")
    proc = run_tasks(repo, "index", "--create", "same")
    assert proc.returncode == 4 and "already exists" in proc.stderr


def test_handle_forms_resolve_to_same_task(repo):
    create(repo, "alpha")
    p = create(repo, "beta")
    store = Store(repo)
    for handle in ("2", "beta", "0002-beta", "0002-beta.md", "tasks/todo/0002-beta.md"):
        assert store.resolve(handle).path == p, handle
    try:
        store.resolve("gamma")
    except TaskError as e:
        assert e.code == 4
    else:
        raise AssertionError("unknown handle must be refused")


def test_assign_gives_index_to_bare_slug_file(repo):
    create(repo, "indexed")
    bare = repo.root / "tasks" / "todo" / "arrived-bare.md"
    bare.write_text("# Arrived\n\ntype: task\n\n## Items\n- [ ] 1. x\n")
    subprocess.run(["git", "add", "tasks/todo/arrived-bare.md"], cwd=repo.root, check=True)
    subprocess.run(["git", "commit", "-qm", "bare"], cwd=repo.root, check=True)
    proc = run_tasks(repo, "index", "--assign")
    assert proc.returncode == 0, proc.stderr
    assert "assigned tasks/todo/0002-arrived-bare.md" in proc.stdout
    assert not bare.exists() and (repo.root / "tasks" / "todo" / "0002-arrived-bare.md").exists()
    assert git(repo.root, "status", "--short") == ""


def test_exclusive_flags_are_rejected(repo):
    assert run_tasks(repo, "index", "--create", "x", "--assign").returncode == 2
    assert run_tasks(repo, "claim", "--slug", "x", "--heartbeat").returncode == 2
