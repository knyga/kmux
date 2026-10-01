#!/usr/bin/env python3
"""Small, credential-safe helpers for the xcodex shell wrapper."""

import base64
import json
import os
import shutil
import sys
from pathlib import Path


SHARED_NAMES = (
    "AGENTS.md",
    "config.toml",
    "hooks.json",
    "rules",
    "skills",
    "themes",
)


def load_json(path):
    try:
        with path.open(encoding="utf-8") as handle:
            value = json.load(handle)
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def jwt_claims(token):
    """Decode local display claims only; this is never an authorization check."""
    try:
        encoded = token.split(".")[1]
        encoded += "=" * (-len(encoded) % 4)
        value = json.loads(base64.urlsafe_b64decode(encoded.encode("ascii")))
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def printable_label(value):
    if not isinstance(value, str):
        return ""
    clean = "".join(character for character in value.strip() if character.isprintable())
    return clean[:160]


def account_label(config_dir):
    auth = load_json(config_dir / "auth.json")
    api_key = auth.get("OPENAI_API_KEY")
    if isinstance(api_key, str) and api_key.strip():
        return "OpenAI API key"

    tokens = auth.get("tokens")
    if not isinstance(tokens, dict):
        return ""

    claims = jwt_claims(tokens.get("id_token", ""))
    for key in ("email", "name"):
        label = printable_label(claims.get(key))
        if label:
            return label

    if tokens.get("refresh_token") or tokens.get("access_token"):
        return "ChatGPT account"
    return ""


def path_exists(path):
    return os.path.lexists(os.fspath(path))


def confirm(message):
    try:
        return input(f"{message} [y/N] ").strip().lower().startswith("y")
    except (EOFError, KeyboardInterrupt):
        print()
        return False


def copy_shared(source, destination):
    source = source.expanduser().resolve()
    destination = destination.expanduser().resolve()
    if source == destination:
        print(f"xcodex-seed: {source} is the source", file=sys.stderr)
        return 1
    if not source.is_dir():
        print(f"xcodex-seed: source directory is missing: {source}", file=sys.stderr)
        return 1

    destination.mkdir(mode=0o700, parents=True, exist_ok=True)
    candidates = [source / name for name in SHARED_NAMES]
    candidates.extend(sorted(source.glob("*.config.toml")))
    copied = 0

    for src in candidates:
        if not path_exists(src):
            continue
        dst = destination / src.name

        if path_exists(dst):
            action = "merge into" if src.is_dir() and not src.is_symlink() else "overwrite"
            if not confirm(f"{action} {dst}?"):
                continue

        try:
            if src.is_symlink():
                if path_exists(dst):
                    print(f"xcodex-seed: refusing to replace symlink: {dst}", file=sys.stderr)
                    continue
                dst.symlink_to(os.readlink(src), target_is_directory=src.is_dir())
            elif src.is_dir():
                if path_exists(dst) and not dst.is_dir():
                    print(f"xcodex-seed: cannot merge a directory into {dst}", file=sys.stderr)
                    continue
                shutil.copytree(src, dst, dirs_exist_ok=True, symlinks=True)
            else:
                if path_exists(dst) and (dst.is_dir() or dst.is_symlink()):
                    print(f"xcodex-seed: refusing to replace non-file path: {dst}", file=sys.stderr)
                    continue
                shutil.copy2(src, dst)
            copied += 1
        except Exception as error:
            print(f"xcodex-seed: could not copy {src}: {error}", file=sys.stderr)
            return 1

    print(f"xcodex-seed: copied or merged {copied} shared item(s) into {destination}")
    return 0


def usage():
    print(
        "usage: xcodex.py identity <config-dir>\n"
        "       xcodex.py seed <source-config-dir> <destination-config-dir>",
        file=sys.stderr,
    )
    return 2


def main():
    if len(sys.argv) == 3 and sys.argv[1] == "identity":
        label = account_label(Path(sys.argv[2]))
        if not label:
            return 1
        print(label)
        return 0
    if len(sys.argv) == 4 and sys.argv[1] == "seed":
        return copy_shared(Path(sys.argv[2]), Path(sys.argv[3]))
    return usage()


if __name__ == "__main__":
    raise SystemExit(main())
