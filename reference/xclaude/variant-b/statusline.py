#!/usr/bin/env python3
"""xclaude status line for Claude Code.

Row 1: account │ model │ branch │ context %
Row 2: rate limits (payload merged with a cached GET /api/oauth/usage)

Claude Code pipes a JSON payload on stdin and prints whatever we write to stdout.
The usage cache never blocks a render: when stale, a detached `--refresh` child is
spawned and this render draws with whatever is already cached.
"""
import hashlib
import json
import os
import subprocess
import sys
import time
import unicodedata
import urllib.request
from datetime import datetime, timezone

HOME = os.path.expanduser("~")
CFG_ENV = os.environ.get("CLAUDE_CONFIG_DIR")
CFG_DIR = CFG_ENV or os.path.join(HOME, ".claude")
CACHE = os.path.join(CFG_DIR, "statusline-usage.json")
LOCK = CACHE + ".lock"
CACHE_TTL = 120       # seconds
LOCK_STALE = 60       # seconds
USAGE_URL = "https://api.anthropic.com/api/oauth/usage"

RESET, DIM, GREEN, YELLOW, RED, CYAN, MAGENTA, BLUE = (
    "\033[0m", "\033[2m", "\033[32m", "\033[33m", "\033[31m", "\033[36m", "\033[35m", "\033[34m")
SEP = f" {DIM}│{RESET} "


# ---------------------------------------------------------------- helpers
def read_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def account_name():
    # Default install: ~/.claude.json. With CLAUDE_CONFIG_DIR set: <dir>/.claude.json.
    candidates = [os.path.join(CFG_DIR, ".claude.json")]
    if not CFG_ENV:
        candidates.insert(0, os.path.join(HOME, ".claude.json"))
    for p in candidates:
        d = read_json(p)
        if isinstance(d, dict):
            acct = d.get("oauthAccount") or {}
            for k in ("emailAddress", "displayName", "fullName"):
                if acct.get(k):
                    return str(acct[k])
    return os.path.basename(CFG_DIR.rstrip("/")) or "?"


def git_branch(cwd):
    if not cwd or not os.path.isdir(cwd):
        return "-"
    def run(*args):
        r = subprocess.run(["git", "-C", cwd, "-c", "gc.auto=0", *args],
                           capture_output=True, text=True, timeout=1)
        return r.stdout.strip() if r.returncode == 0 else ""
    try:
        # symbolic-ref works on an unborn branch (repo with no commits yet).
        b = run("symbolic-ref", "--short", "-q", "HEAD")
        if b:
            return b
        if not run("rev-parse", "--is-inside-work-tree"):
            return "-"
        return run("rev-parse", "--short", "HEAD") or "HEAD"   # detached
    except Exception:
        return "-"


def parse_ts(v):
    """-> epoch seconds from an ISO-8601 string or a numeric epoch (s or ms)."""
    if v is None:
        return None
    try:
        if isinstance(v, (int, float)):
            n = float(v)
            return n / 1000 if n > 1e11 else n
        s = str(v).strip()
        if s.replace(".", "", 1).isdigit():
            n = float(s)
            return n / 1000 if n > 1e11 else n
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except Exception:
        return None


def delta(ts):
    if ts is None:
        return ""
    s = int(ts - time.time())
    if s < 60:
        return "<1m"
    d, s = divmod(s, 86400)
    h, s = divmod(s, 3600)
    m = s // 60
    if d:
        return f"{d}d{h}h"
    if h:
        return f"{h}h{m}m"
    return f"{m}m"


def color_pct(p):
    c = GREEN if p < 60 else YELLOW if p < 80 else RED
    return f"{c}{int(round(p))}%{RESET}"


def gauge(label, pct, resets):
    s = f"{label} {color_pct(pct)}"
    dl = delta(resets)
    if dl:
        s += f" {DIM}({dl}){RESET}"
    return s


# ---------------------------------------------------------------- credentials
def keychain_service():
    if os.environ.get("XCLAUDE_KEYCHAIN_SERVICE"):
        return os.environ["XCLAUDE_KEYCHAIN_SERVICE"]
    if not CFG_ENV:
        return "Claude Code-credentials"
    h = hashlib.sha256(unicodedata.normalize("NFC", CFG_ENV).encode()).hexdigest()[:8]
    return f"Claude Code-credentials-{h}"


def load_credentials():
    d = read_json(os.path.join(CFG_DIR, ".credentials.json"))
    if isinstance(d, dict):
        return d
    if sys.platform == "darwin":
        svc = keychain_service()
        for acct in (os.environ.get("USER") or "claude-code-user", "claude-code-user"):
            try:
                r = subprocess.run(["security", "find-generic-password", "-s", svc, "-a", acct, "-w"],
                                   capture_output=True, text=True, timeout=5)
                if r.returncode == 0 and r.stdout.strip():
                    return json.loads(r.stdout)
            except Exception:
                pass
    return None


def access_token():
    creds = load_credentials()
    if not creds:
        return None
    oauth = creds.get("claudeAiOauth") or {}
    tok = oauth.get("accessToken")
    exp = oauth.get("expiresAt")
    if not tok:
        return None
    if exp and float(exp) / 1000 <= time.time():
        return None   # expired: Claude Code refreshes it itself; never rotate here
    return tok


# ---------------------------------------------------------------- cache / refresh
def read_cache():
    c = read_json(CACHE)
    return c if isinstance(c, dict) else {}


def write_cache(obj):
    tmp = CACHE + f".tmp{os.getpid()}"
    try:
        os.makedirs(CFG_DIR, exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(obj, f)
        os.replace(tmp, CACHE)
    except Exception:
        try:
            os.unlink(tmp)
        except Exception:
            pass


def acquire_lock():
    for _ in range(2):
        try:
            fd = os.open(LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            return True
        except FileExistsError:
            try:
                if time.time() - os.stat(LOCK).st_mtime > LOCK_STALE:
                    os.unlink(LOCK)     # steal from a dead refresher
                    continue
            except FileNotFoundError:
                continue
            except Exception:
                pass
            return False
        except Exception:
            return False
    return False


def refresh():
    if not acquire_lock():
        return
    try:
        old = read_cache()
        out = {"fetched_at": time.time(), "data": old.get("data")}
        tok = access_token()
        if not tok:
            out["error"] = "no token"
        else:
            req = urllib.request.Request(USAGE_URL, headers={
                "Authorization": f"Bearer {tok}",
                "anthropic-beta": "oauth-2025-04-20",
                "Accept": "application/json",
                "User-Agent": "xclaude-statusline",
            })
            try:
                with urllib.request.urlopen(req, timeout=8) as r:
                    data = json.loads(r.read().decode("utf-8"))
                if isinstance(data, dict):
                    out["data"] = data
                else:
                    out["error"] = "malformed"
            except Exception as e:
                out["error"] = str(e)[:200]
        write_cache(out)
    finally:
        try:
            os.unlink(LOCK)
        except Exception:
            pass


def spawn_refresh():
    try:
        subprocess.Popen([sys.executable or "python3", os.path.abspath(__file__), "--refresh"],
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True, close_fds=True)
    except Exception:
        pass


# ---------------------------------------------------------------- gauges
def cache_gauges(data):
    """-> ordered list of (key, label, pct, resets_epoch) from the usage API body."""
    out = []
    limits = data.get("limits") if isinstance(data, dict) else None
    if isinstance(limits, list) and limits:
        for lim in limits:
            if not isinstance(lim, dict) or lim.get("percent") is None:
                continue
            kind = lim.get("kind")
            rs = parse_ts(lim.get("resets_at"))
            if kind == "session":
                out.append(("session", "session", float(lim["percent"]), rs))
            elif kind == "weekly_all":
                out.append(("week", "week", float(lim["percent"]), rs))
            elif kind == "weekly_scoped":
                name = (((lim.get("scope") or {}).get("model") or {}).get("display_name")) or "scoped"
                out.append((f"scoped:{name}", str(name), float(lim["percent"]), rs))
        return out
    # Legacy top-level shape.
    for key, label in (("five_hour", "session"), ("seven_day", "week"),
                       ("seven_day_opus", "Opus"), ("seven_day_sonnet", "Sonnet")):
        v = data.get(key) if isinstance(data, dict) else None
        if isinstance(v, dict) and v.get("utilization") is not None:
            k = label if label in ("session", "week") else f"scoped:{label}"
            out.append((k, label, float(v["utilization"]), parse_ts(v.get("resets_at"))))
    return out


def payload_gauges(payload):
    out = []
    rl = payload.get("rate_limits") if isinstance(payload, dict) else None
    if not isinstance(rl, dict):
        return out
    for key, label in (("five_hour", "session"), ("seven_day", "week"), ("spend_limit", "spend")):
        v = rl.get(key)
        if isinstance(v, dict) and v.get("used_percentage") is not None:
            out.append((label, label, float(v["used_percentage"]), parse_ts(v.get("resets_at"))))
    return out


def row2(payload):
    cache = read_cache()
    age = time.time() - float(cache.get("fetched_at") or 0)
    if age > CACHE_TTL:
        spawn_refresh()
    merged = {}
    order = []
    for k, label, pct, rs in cache_gauges(cache.get("data") or {}):
        if k not in merged:
            order.append(k)
        merged[k] = (label, pct, rs)
    for k, label, pct, rs in payload_gauges(payload):     # payload wins: freshest
        if k not in merged:
            order.append(k)
        merged[k] = (label, pct, rs)
    # session, week first; then the rest in API order.
    order.sort(key=lambda k: {"session": 0, "week": 1}.get(k, 2))
    if not order:
        return f"⏱ {DIM}no usage data{RESET}"
    return "⏱ " + SEP.join(gauge(*merged[k]) for k in order)


# ---------------------------------------------------------------- main
def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--refresh":
        refresh()
        return
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    model = ((payload.get("model") or {}).get("display_name")) or "?"
    ws = payload.get("workspace") or {}
    cwd = ws.get("current_dir") or payload.get("cwd") or os.getcwd()
    ctx = (payload.get("context_window") or {}).get("used_percentage") or 0
    try:
        ctx = int(round(float(ctx)))
    except Exception:
        ctx = 0

    who = account_name()
    prof = os.environ.get("XCLAUDE_PROFILE")
    if prof and prof != who:
        who = f"{who} {DIM}({prof} profile){RESET}"
    row1 = SEP.join([
        f"👤 {CYAN}{who}{RESET}",
        f"◆ {MAGENTA}{model}{RESET}",
        f"⎇ {BLUE}{git_branch(cwd)}{RESET}",
        f"▮ ctx {color_pct(ctx)}",
    ])
    sys.stdout.write(row1 + "\n" + row2(payload) + "\n")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:   # never break the status line
        sys.stdout.write(f"👤 xclaude statusline error: {str(e)[:80]}\n")
