#!/usr/bin/env python3
"""Shared Claude Code status line for every xclaude config dir.

Line 1: account email | model | git branch | context used % | local time (+ LA time)
Line 2: rate limits (session / weekly / per-model scoped): usage %, the % of the
        window's clock already spent, and the time left before it resets

The rate-limit numbers come from two sources:
  * the statusLine payload's `rate_limits` (live, free, but only 5h + 7d), and
  * a cached GET /api/oauth/usage (adds the per-model weekly limits, e.g. Fable).
The cache is refreshed by a detached background process, so rendering never
blocks on the network. If the OAuth token is expired we simply skip the fetch --
Claude Code itself refreshes `.credentials.json`, we never rotate it ourselves.
"""
import json
import os
import subprocess
import sys
import time

CACHE_TTL = 120          # seconds before the usage cache is considered stale
LOCK_TTL = 60            # seconds before a stuck refresh lock is stolen
FETCH_TIMEOUT = 8

R = "\033[0m"
DIM = "\033[2m"
CYAN = "\033[36m"
MAGENTA = "\033[35m"
BLUE = "\033[34m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
GRAY = "\033[90m"
SEP = f" {DIM}│{R} "


def config_dir() -> str:
    return os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude")


def load_json(path):
    try:
        with open(path) as fh:
            return json.load(fh)
    except Exception:
        return None


# --------------------------------------------------------------------------- #
# background refresh of /api/oauth/usage
# --------------------------------------------------------------------------- #
def read_oauth(cfg):
    """OAuth block from `.credentials.json`, or the macOS login Keychain.

    Linux/WSL always store credentials as plaintext JSON in the config dir.
    macOS keeps them in the Keychain instead; the service name is not stable
    across config dirs, so override it with XCLAUDE_KEYCHAIN_SERVICE when the
    default guess is wrong (find it with:
    `security dump-keychain | grep -i "svce.*[Cc]redentials"`).
    """
    creds = load_json(os.path.join(cfg, ".credentials.json"))
    if creds:
        return creds.get("claudeAiOauth") or {}
    if sys.platform != "darwin":
        return {}
    service = os.environ.get("XCLAUDE_KEYCHAIN_SERVICE", "Claude Code-credentials")
    try:
        raw = subprocess.run(
            ["security", "find-generic-password", "-a", "claude-code-user", "-w", "-s", service],
            capture_output=True, text=True, timeout=10,
        ).stdout.strip()
        return (json.loads(raw) or {}).get("claudeAiOauth") or {}
    except Exception:
        return {}


def cache_path(cfg):
    return os.path.join(cfg, "statusline-usage.json")


def refresh_usage(cfg):
    """Fetch the usage endpoint and write it to the cache. Runs detached."""
    import urllib.request

    lock = cache_path(cfg) + ".lock"
    try:
        if os.path.exists(lock) and time.time() - os.path.getmtime(lock) > LOCK_TTL:
            os.unlink(lock)
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(fd)
    except FileExistsError:
        return
    except Exception:
        return

    try:
        oauth = read_oauth(cfg)
        token = oauth.get("accessToken")
        expires = oauth.get("expiresAt")
        if not token or (isinstance(expires, (int, float)) and expires / 1000 <= time.time()):
            return
        req = urllib.request.Request(
            "https://api.anthropic.com/api/oauth/usage",
            headers={
                "Authorization": f"Bearer {token}",
                "anthropic-beta": "oauth-2025-04-20",
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT) as resp:
            body = json.loads(resp.read().decode())
        tmp = cache_path(cfg) + f".tmp.{os.getpid()}"
        with open(tmp, "w") as fh:
            json.dump({"fetched_at": time.time(), "usage": body}, fh)
        os.replace(tmp, cache_path(cfg))
    except Exception:
        pass
    finally:
        try:
            os.unlink(lock)
        except Exception:
            pass


def read_usage_cache(cfg):
    """Return the cached usage body, kicking off a background refresh if stale."""
    cached = load_json(cache_path(cfg))
    age = time.time() - cached["fetched_at"] if cached and "fetched_at" in cached else 1e9
    if age > CACHE_TTL:
        try:
            subprocess.Popen(
                [sys.executable, os.path.abspath(__file__), "--refresh"],
                start_new_session=True,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=dict(os.environ, CLAUDE_CONFIG_DIR=cfg),
            )
        except Exception:
            pass
    return (cached or {}).get("usage") or {}


# --------------------------------------------------------------------------- #
# formatting
# --------------------------------------------------------------------------- #
def pct_color(pct):
    if pct >= 80:
        return RED
    if pct >= 60:
        return YELLOW
    return GREEN


SESSION_WINDOW = 5 * 3600          # the "five_hour" limit
WEEK_WINDOW = 7 * 86400            # "seven_day" + the per-model weekly scopes


def elapsed_pct(resets, window):
    """% of the limit window already burnt, from the reset time it ends at."""
    if resets is None or not window:
        return None
    left = resets - time.time()
    if left < 0:
        left = 0
    if left > window:
        return None                # reset further out than the window: not ours
    return max(0.0, min(100.0, (window - left) / window * 100))


def pace_color(pct, spent):
    """Dim while usage tracks the clock; warn when it runs ahead of it."""
    ahead = pct - spent
    if ahead >= 25:
        return RED
    if ahead >= 10:
        return YELLOW
    return GRAY


def until(epoch):
    """Compact time-to-reset, e.g. 3d1h / 4h13m / 45m / <1m."""
    if epoch is None:
        return None
    left = int(epoch - time.time())
    if left <= 0:
        return "now"
    d, rem = divmod(left, 86400)
    h, rem = divmod(rem, 3600)
    m = rem // 60
    if d:
        return f"{d}d{h}h"
    if h:
        return f"{h}h{m:02d}m"
    if m:
        return f"{m}m"
    return "<1m"


LA_TZ = "America/Los_Angeles"


def clocks():
    """`HH:MM TZ` for the local zone, plus LA time when it is a different zone."""
    from datetime import datetime

    now = datetime.now().astimezone()
    out = [f"{GRAY}\U0001f550 {now:%H:%M} {now:%Z}{R}"]
    try:
        from zoneinfo import ZoneInfo

        la = datetime.now(ZoneInfo(LA_TZ))
    except Exception:
        return out
    if la.utcoffset() != now.utcoffset():
        out.append(f"{GRAY}\U0001f1fa\U0001f1f8 {la:%H:%M} {la:%Z}{R}")
    return out


def parse_ts(value):
    """Accept unix seconds (payload) or an ISO-8601 string (usage API)."""
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str) and value:
        try:
            from datetime import datetime

            return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
        except Exception:
            return None
    return None


def collect_limits(payload, usage):
    """[(label, percent, resets_at_epoch, window_seconds)] -- payload wins for
    session/weekly. window_seconds is the limit period's full length, so the
    caller can turn a reset time into "how much of this window is gone".
    """
    out, seen = [], set()

    rl = payload.get("rate_limits") or {}
    for key, label, window in (
        ("five_hour", "session", SESSION_WINDOW),
        ("seven_day", "week", WEEK_WINDOW),
    ):
        entry = rl.get(key)
        if isinstance(entry, dict) and entry.get("used_percentage") is not None:
            out.append((label, float(entry["used_percentage"]), parse_ts(entry.get("resets_at")), window))
            seen.add(label)

    for item in usage.get("limits") or []:
        if not isinstance(item, dict):
            continue
        kind = item.get("kind")
        if kind == "session":
            label, window = "session", SESSION_WINDOW
        elif kind == "weekly_all":
            label, window = "week", WEEK_WINDOW
        elif kind == "weekly_scoped":
            label = ((item.get("scope") or {}).get("model") or {}).get("display_name") or "scoped"
            window = WEEK_WINDOW
        else:
            continue
        if label in seen:
            continue
        seen.add(label)
        out.append((label, float(item.get("percent") or 0), parse_ts(item.get("resets_at")), window))

    spend = usage.get("spend") or {}
    if spend.get("enabled"):
        out.append(("credits", float(spend.get("percent") or 0), None, None))

    order = {"session": 0, "week": 1, "credits": 9}
    out.sort(key=lambda t: (order.get(t[0], 5), t[0]))
    return out


def main():
    cfg = config_dir()

    if "--refresh" in sys.argv[1:]:
        refresh_usage(cfg)
        return

    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except Exception:
        payload = {}

    account = "?"
    acct = (load_json(os.path.join(cfg, ".claude.json")) or {}).get("oauthAccount") or {}
    for key in ("emailAddress", "displayName", "fullName"):
        if acct.get(key):
            account = acct[key]
            break

    model = (payload.get("model") or {}).get("display_name") or (payload.get("model") or {}).get("id") or "?"
    ctx = int((payload.get("context_window") or {}).get("used_percentage") or 0)
    cwd = (payload.get("workspace") or {}).get("current_dir") or payload.get("cwd") or "."

    branch = "-"
    try:
        branch = subprocess.run(
            ["git", "-C", cwd, "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, timeout=2,
        ).stdout.strip() or "-"
        if branch == "HEAD":
            branch = subprocess.run(
                ["git", "-C", cwd, "rev-parse", "--short", "HEAD"],
                capture_output=True, text=True, timeout=2,
            ).stdout.strip() or "detached"
    except Exception:
        pass

    line1 = SEP.join([
        f"{CYAN}\U0001f464 {account}{R}",
        f"{MAGENTA}◆ {model}{R}",
        f"{BLUE}⎇ {branch}{R}",
        f"{pct_color(ctx)}▮ ctx {ctx}%{R}",
        *clocks(),
    ])

    limits = collect_limits(payload, read_usage_cache(cfg))
    if limits:
        parts = []
        for label, pct, resets, window in limits:
            reset = until(resets)
            spent = elapsed_pct(resets, window)
            if reset and spent is not None:
                clock = f"{pace_color(pct, spent)}t{int(spent)}%{R}{DIM} · {reset}{R}"
                tail = f" {DIM}({R}{clock}{DIM}){R}"
            elif reset:
                tail = f" {DIM}({reset}){R}"
            else:
                tail = ""
            parts.append(f"{pct_color(pct)}{label} {int(pct)}%{R}{tail}")
        line2 = f"{DIM}⏱{R} " + SEP.join(parts)
    else:
        line2 = f"{DIM}⏱ limits: waiting for first API response…{R}"

    sys.stdout.write(line1 + "\n" + line2 + "\n")


if __name__ == "__main__":
    main()
