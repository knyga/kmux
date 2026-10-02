"""Process liveness and session identity.

A lease is "live" on this host exactly while its recorded pid is alive. The CLI process itself exits
immediately, so the pid we record must be the *session's* long-lived ancestor (the Claude Code
process, or the interactive shell / terminal in a manual session). ``TASKS_PID`` overrides the walk.
"""

from __future__ import annotations

import os
import socket
import subprocess
import time

# Short-lived wrappers we walk past when looking for the session process.
_TRANSIENT = {
    "sh", "bash", "zsh", "fish", "dash", "ksh", "python", "python3", "python3.11", "python3.12",
    "python3.13", "tasks", "uv", "nohup", "env", "caffeinate", "timeout", "script", "time",
}


def hostname() -> str:
    return os.environ.get("TASKS_HOST") or socket.gethostname()


def pid_alive(pid: int | None) -> bool:
    if not pid or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _parse_etime(text: str) -> int | None:
    """``ps -o etime`` -> seconds. Format ``[[dd-]hh:]mm:ss`` on both macOS and Linux."""
    text = text.strip()
    if not text:
        return None
    days = 0
    if "-" in text:
        d, text = text.split("-", 1)
        days = int(d)
    parts = [int(x) for x in text.split(":")]
    if len(parts) == 2:
        h, m, sec = 0, *parts
    elif len(parts) == 3:
        h, m, sec = parts
    else:
        return None
    return days * 86400 + h * 3600 + m * 60 + sec


def proc_start(pid: int | None) -> str:
    """Start time of ``pid`` as integer epoch seconds (string), derived from ``ps -o etime=`` anchored
    to ``time.time()`` — numeric, so locale and timezone cannot change it. "" when unknown."""
    if not pid or pid <= 0:
        return ""
    try:
        out = subprocess.run(["ps", "-o", "etime=", "-p", str(pid)], text=True, capture_output=True,
                             timeout=5, env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LC_ALL": "C"}).stdout
        elapsed = _parse_etime(out)
    except (OSError, subprocess.SubprocessError, ValueError):
        return ""
    if elapsed is None:
        return ""
    return str(round(time.time() - elapsed))


def proc_start_matches(pid: int | None, recorded: str, tolerance: int = 2) -> bool:
    """True when ``pid`` started when ``recorded`` says (±tolerance s). A non-numeric or empty record
    (older lease shape, or ps unavailable) is treated as unknown -> True (fail open on evidence)."""
    if not recorded or not recorded.strip().lstrip("-").isdigit():
        return True
    now = proc_start(pid)
    if not now:
        return True
    return abs(int(now) - int(recorded)) <= tolerance


def _parent_and_comm(pid: int) -> tuple[int, str] | None:
    try:
        out = subprocess.run(["ps", "-o", "ppid=,comm=", "-p", str(pid)], text=True,
                             capture_output=True, timeout=5).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None
    if not out:
        return None
    parts = out.split(None, 1)
    try:
        ppid = int(parts[0])
    except ValueError:
        return None
    comm = os.path.basename(parts[1].strip()) if len(parts) > 1 else ""
    return ppid, comm


def session_pid() -> int:
    env = os.environ.get("TASKS_PID")
    if env:
        try:
            return int(env)
        except ValueError:
            pass
    pid = os.getpid()
    fallback = os.getppid()
    for _ in range(12):
        info = _parent_and_comm(pid)
        if info is None:
            break
        ppid, _comm = info
        if ppid <= 1:
            break
        pinfo = _parent_and_comm(ppid)
        if pinfo is None:
            break
        _, pcomm = pinfo
        if pcomm.lower() not in _TRANSIENT:
            return ppid
        pid = ppid
    return fallback
