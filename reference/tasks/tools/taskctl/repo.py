"""Repository locations and a thin git wrapper.

Every tracker mutation happens in the *main* checkout, even when the CLI is invoked from inside a
worktree under ``.worktrees/``: ``find_root`` resolves ``git rev-parse --git-common-dir`` and takes its
parent. Env ``TASKS_REPO`` overrides (tests, unusual layouts).
"""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

STATUSES = ("todo", "in_progress", "human_action_required", "done", "cancelled")
TERMINAL = ("done", "cancelled")

EXIT_OK = 0
EXIT_REFUSED_GATE = 2
EXIT_NOTHING = 3
EXIT_REFUSED = 4


class TaskError(Exception):
    """A user-facing refusal; ``code`` becomes the process exit status."""

    def __init__(self, message: str, code: int = 1):
        super().__init__(message)
        self.code = code


def warn(msg: str) -> None:
    print(f"warning: {msg}", file=sys.stderr)


def run(cmd: list[str], cwd: Path, *, check: bool = True) -> subprocess.CompletedProcess:
    proc = subprocess.run(cmd, cwd=str(cwd), text=True, capture_output=True)
    if check and proc.returncode != 0:
        raise TaskError(
            f"command failed ({proc.returncode}): {' '.join(cmd)}\n{proc.stderr.strip() or proc.stdout.strip()}"
        )
    return proc


def find_root(start: Path | None = None) -> Path:
    env = os.environ.get("TASKS_REPO")
    if env:
        return Path(env).resolve()
    cwd = (start or Path.cwd()).resolve()
    proc = run(["git", "rev-parse", "--git-common-dir"], cwd, check=False)
    if proc.returncode != 0:
        raise TaskError("not inside a git repository (set TASKS_REPO to point at one)")
    common = Path(proc.stdout.strip())
    if not common.is_absolute():
        common = cwd / common
    return common.resolve().parent


@dataclass(frozen=True)
class Repo:
    root: Path

    @classmethod
    def discover(cls, start: Path | None = None) -> Repo:
        return cls(find_root(start))

    # locations -------------------------------------------------------------------------------
    @property
    def tasks_dir(self) -> Path:
        return self.root / "tasks"

    def folder(self, status: str) -> Path:
        if status not in STATUSES:
            raise TaskError(f"unknown status {status!r}")
        return self.tasks_dir / status

    @property
    def leases_dir(self) -> Path:
        return self.tasks_dir / ".leases"

    @property
    def lock_dir(self) -> Path:
        return self.tasks_dir / ".claim.lock"

    @property
    def worktrees_dir(self) -> Path:
        return self.root / ".worktrees"

    @property
    def loop_state_path(self) -> Path:
        return self.root / ".solve-loop" / "state.json"

    def rel(self, path: Path) -> str:
        return os.path.relpath(path, self.root)

    # git -----------------------------------------------------------------------------------
    def git(self, *args: str, check: bool = True, cwd: Path | None = None) -> subprocess.CompletedProcess:
        return run(["git", *args], cwd or self.root, check=check)

    def git_out(self, *args: str, cwd: Path | None = None) -> str:
        return self.git(*args, cwd=cwd).stdout.strip()

    @property
    def main_branch(self) -> str:
        env = os.environ.get("TASKS_MAIN_BRANCH")
        if env:
            return env
        for name in ("main", "master"):
            if self.branch_exists(name):
                return name
        return "main"

    def branch_exists(self, name: str) -> bool:
        return self.git("rev-parse", "--verify", "--quiet", f"refs/heads/{name}", check=False).returncode == 0

    def current_branch(self) -> str:
        return self.git_out("rev-parse", "--abbrev-ref", "HEAD")

    def is_tracked(self, path: Path) -> bool:
        return self.git("ls-files", "--error-unmatch", "--", self.rel(path), check=False).returncode == 0

    def in_index(self, rel: str) -> bool:
        return self.git("ls-files", "--error-unmatch", "--", rel, check=False).returncode == 0

    def commit_paths(self, message: str, paths: list[Path]) -> str:
        """Stage and commit exactly ``paths`` — additions, edits AND deletions — with an explicit pathspec.

        Nothing is staged before this call (``move`` is a plain rename), so the index is never left
        dirty between steps and other dirty files in the checkout are never swept in.
        """
        rels = [self.rel(p) for p in paths]
        spec = [r for r in rels if (self.root / r).exists() or self.in_index(r)]
        if not spec:
            raise TaskError(f"nothing to commit for {message!r}")
        self.git("add", "-A", "--", *spec)
        self.git("-c", "commit.gpgsign=false", "commit", "-q", "-m", message, "--", *spec)
        return self.git_out("rev-parse", "--short", "HEAD")

    def staged_paths(self) -> list[str]:
        """Paths whose index entry differs from HEAD (a non-empty list blocks landing)."""
        return [ln for ln in self.git_out("diff", "--cached", "--name-only").splitlines() if ln]

    def move(self, src: Path, dst: Path) -> None:
        """Plain rename; the deletion + addition are staged together by ``commit_paths``."""
        dst.parent.mkdir(parents=True, exist_ok=True)
        os.replace(src, dst)

    def added_timestamp(self, path: Path) -> float:
        """Unix time of the commit that ADDED the file (follows renames); mtime fallback."""
        proc = self.git("log", "--diff-filter=A", "--follow", "--format=%ct", "--", self.rel(path), check=False)
        lines = [ln for ln in proc.stdout.split() if ln.strip()]
        if lines:
            try:
                return float(lines[-1])
            except ValueError:
                pass
        try:
            return path.stat().st_mtime
        except OSError:
            return 0.0

    def last_commit_timestamp(self, path: Path) -> float | None:
        proc = self.git("log", "-1", "--format=%ct", "--", self.rel(path), check=False)
        out = proc.stdout.strip()
        try:
            return float(out) if out else None
        except ValueError:
            return None

    # worktrees -----------------------------------------------------------------------------
    def worktree_paths(self) -> dict[str, Path]:
        """branch name -> worktree path for every registered worktree."""
        out = self.git_out("worktree", "list", "--porcelain")
        result: dict[str, Path] = {}
        path: Path | None = None
        for line in out.splitlines():
            if line.startswith("worktree "):
                path = Path(line[len("worktree "):])
            elif line.startswith("branch ") and path is not None:
                result[line[len("branch "):].removeprefix("refs/heads/")] = path
        return result
