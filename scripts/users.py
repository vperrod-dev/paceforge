#!/usr/bin/env python3
"""Manage per-athlete PaceForge instances.

Sharing the portal is process isolation, not multi-tenancy in the app: each
athlete gets their own checkout, their own ``data/``, their own Garmin token dir
and their own runner port, all behind one Caddy path. Nothing in the app has to
learn about users, and one athlete's job can never touch another's files.

    scripts/users.py add alice          # provision + start + print credentials
    scripts/users.py list
    scripts/users.py update [alice]     # pull code from the main checkout, restart
    scripts/users.py remove alice --yes

Victor's own instance is the un-templated ``paceforge-runner`` unit on 8123 and is
never touched by this script.
"""

# ruff: noqa: S603, S607  (fixed argv lists; the one interpolated value, the
# instance name, is validated against NAME_RE before it reaches any command)

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
from pathlib import Path

HOME = Path.home()
MAIN = Path(__file__).resolve().parent.parent          # Victor's checkout
USERS = HOME / "projects" / "paceforge-users"
ENV_DIR = HOME / ".config" / "paceforge"
UNIT_DIR = HOME / ".config" / "systemd" / "user"
CADDYFILE = Path("/etc/caddy/Caddyfile")
HOST = os.environ.get("PF_HOST", "claude-dev-vperrod.westeurope.cloudapp.azure.com")
FIRST_PORT = 8124                                       # 8123 is Victor's
# \Z, not a trailing $ — Python's $ matches before a final newline, so "alice\n"
# would otherwise pass and carry an embedded newline into a systemd unit name,
# a URL path or a Caddyfile block.
NAME_RE = re.compile(r"^[a-z][a-z0-9-]{1,20}\Z")
UNITS = ("paceforge-runner@{n}", "paceforge-sync@{n}.timer",
         "paceforge-autosync@{n}.timer", "paceforge-coach@{n}.timer")
# What an instance runs from its own checkout. src/ is absent on purpose: the venv
# is shared and installs paceforge editable from the main checkout, so the Python
# package is already the same code everywhere.
CODE_DIRS = ("web", "scripts", "ops", ".claude", "data/bike/workouts")
KEEP_IN_DATA = ("data/bike/workouts/",)   # shipped workout library, not athlete data
# The instance name lands in a URL path, a systemd unit name, a filename and the
# Caddyfile — validate once, here, and everything downstream is safe.
BAD_NAME = "name must be lowercase letters/digits/dashes, 2-21 chars, e.g. 'alice'"


def run(cmd: list[str], cwd: Path | None = None, check: bool = True) -> str:
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if check and p.returncode != 0:
        sys.exit(f"! {' '.join(cmd)}\n{p.stdout}{p.stderr}")
    return p.stdout.strip()


def git_commit(cwd: Path, msg: str) -> bool:
    """Commit everything in an instance. False when there was nothing to commit."""
    run(["git", "add", "-A"], cwd=cwd)
    if subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=cwd).returncode == 0:
        return False
    run(["git", "-c", "user.name=paceforge-bot", "-c", "user.email=bot@paceforge.local",
         "commit", "-qm", msg], cwd=cwd)
    return True


def instances() -> list[str]:
    return sorted(d.name for d in USERS.glob("*") if (d / "scripts" / "runner.py").exists())


def env_of(name: str) -> dict[str, str]:
    f = ENV_DIR / f"{name}.env"
    if not f.exists():
        return {}
    return dict(line.split("=", 1) for line in f.read_text().splitlines()
                if "=" in line and not line.startswith("#"))


def free_port() -> int:
    used = {int(env_of(n).get("PACEFORGE_RUNNER_PORT", 0)) for n in instances()}
    for port in range(FIRST_PORT, FIRST_PORT + 50):
        if port in used:
            continue
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", port)) != 0:
                return port
    sys.exit("! no free port in range")


def scrypt_conf(password: str) -> str:
    """'<salt_hex>$<hash_hex>' — the format check_login() in runner.py expects."""
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1)
    return f"{salt.hex()}${digest.hex()}"


# ── Caddy ────────────────────────────────────────────────────────────────────

def caddy_block(name: str, port: int) -> str:
    return (f"\t# paceforge-user:{name}\n"
            f"\thandle_path /pf/{name}* {{\n"
            f"\t\treverse_proxy 127.0.0.1:{port}\n"
            f"\t}}\n")


def caddy_edit(add: str | None = None, drop: str | None = None) -> None:
    text = sudo_read(CADDYFILE)
    if drop:
        # The body match excludes lines starting a *different* user's marker, so a
        # block missing its own closing brace (hand-edited, truncated) fails to
        # match at all instead of eating through into — and deleting — the next
        # instance's block.
        pattern = re.compile(
            rf"\t# paceforge-user:{re.escape(drop)}\n"
            rf"(?:(?!\t# paceforge-user:).*?\n)*?\t\}}\n")
        new, n = pattern.subn("", text)
        if not n:
            print(f"  caddy: no block for {drop}")
            return
    else:
        anchor = "\thandle_path /paceforge* {\n\t\treverse_proxy 127.0.0.1:8123\n\t}\n"
        if anchor not in text:
            sys.exit("! could not find the /paceforge block in the Caddyfile — add the "
                     f"route by hand:\n{add}")
        new = text.replace(anchor, anchor + "\n" + add, 1)
    run(["sudo", "-n", "cp", str(CADDYFILE), f"{CADDYFILE}.bak-paceforge-users"])
    subprocess.run(["sudo", "-n", "tee", str(CADDYFILE)], input=new, text=True,
                   check=True, stdout=subprocess.DEVNULL)
    run(["sudo", "-n", "caddy", "validate", "--config", str(CADDYFILE)])
    run(["sudo", "-n", "systemctl", "reload", "caddy"])


def sudo_read(path: Path) -> str:
    return subprocess.run(["sudo", "-n", "cat", str(path)], capture_output=True,
                          text=True, check=True).stdout


# ── commands ─────────────────────────────────────────────────────────────────

def cmd_add(args: argparse.Namespace) -> None:
    name = args.name
    if not NAME_RE.match(name):
        sys.exit(f"! {BAD_NAME}")
    dest = USERS / name
    if dest.exists():
        sys.exit(f"! {dest} already exists — remove it first or pick another name")
    port = args.port or free_port()
    password = args.password or secrets.token_urlsafe(12)

    print(f"→ cloning {MAIN} → {dest}")
    branch = run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=MAIN)
    USERS.mkdir(parents=True, exist_ok=True)
    run(["git", "clone", "--quiet", "--depth", "1", "--branch", branch,
         f"file://{MAIN}", str(dest)])
    # No remotes at all: the instance's git is its own data history on this VM,
    # and nothing may ever push an athlete's data into another's repo. Code
    # updates arrive by file copy instead (see `update`).
    run(["git", "remote", "remove", "origin"], cwd=dest)

    print("→ clearing the inherited athlete data")
    tracked = [t for t in run(["git", "ls-files", "data", "plan.md", "week-review.md"],
                              cwd=dest).split("\n")
               if t and not t.startswith(KEEP_IN_DATA)]
    if tracked:
        run(["git", "rm", "-rq", "--", *tracked], cwd=dest)
    (dest / "data").mkdir(exist_ok=True)
    git_commit(dest, f"instance: fresh data for {name}")

    # The venv is shared: paceforge is installed editable, so every instance runs
    # the main checkout's Python code and a fix lands everywhere at once. Only
    # runner.py, web/ and .claude/ come from the clone (runner.py resolves its own
    # path to find the instance root, so it cannot be a symlink).
    (dest / ".venv").symlink_to(MAIN / ".venv")

    state_dir = HOME / ".local" / "state" / f"paceforge-{name}"
    token_dir = ENV_DIR / f"garmin-{name}"
    for d in (state_dir, token_dir):
        d.mkdir(parents=True, exist_ok=True)
        d.chmod(0o700)

    print("→ writing the instance env file")
    env_file = ENV_DIR / f"{name}.env"
    # No TG_TOKEN/TG_CHAT_ID: telegram() no-ops without them, so friends get no
    # notifications and Victor's chat stays his own.
    env_file.write_text(
        f"PF_WEB_USER={name}\n"
        f"PF_WEB_PASS_SCRYPT={scrypt_conf(password)}\n"
        f"PF_COOKIE_PATH=/pf/{name}\n"
        f"PACEFORGE_RUNNER_PORT={port}\n"
        f"PACEFORGE_RUNNER_INTERNAL_PORT={port + 100}\n"
        f"PACEFORGE_RUNNER_STATE={state_dir}\n"
        f"PACEFORGE_GARMIN_TOKEN_DIR={token_dir}\n"
        f"PF_GARMIN_PROXY={env_of('env').get('PF_GARMIN_PROXY', '')}\n")
    env_file.chmod(0o600)

    print("→ installing + starting the systemd units")
    UNIT_DIR.mkdir(parents=True, exist_ok=True)
    for unit in MAIN.glob("ops/paceforge-*@.*"):
        target = UNIT_DIR / unit.name
        if not target.exists():
            target.symlink_to(unit)
    run(["systemctl", "--user", "daemon-reload"])
    run(["systemctl", "--user", "enable", "--now", *[u.format(n=name) for u in UNITS]])

    print("→ adding the Caddy route")
    caddy_edit(add=caddy_block(name, port))

    print(f"\n✅ {name} is live\n"
          f"   URL:      https://{HOST}/pf/{name}/\n"
          f"   username: {name}\n"
          f"   password: {password}\n"
          f"   port:     {port}   ·   data: {dest}/data\n"
          f"   Next: they open the URL, sign in, then Settings → Connect Garmin "
          f"(their own Garmin account).")


def cmd_list(_: argparse.Namespace) -> None:
    names = instances()
    if not names:
        print("no instances yet — scripts/users.py add <name>")
        return
    for name in names:
        env = env_of(name)
        state = run(["systemctl", "--user", "is-active", f"paceforge-runner@{name}"],
                    check=False) or "unknown"
        rides = USERS / name / "data" / "activities.json"
        count = len(json.loads(rides.read_text())) if rides.exists() else 0
        print(f"{name:12} port {env.get('PACEFORGE_RUNNER_PORT','?'):5} {state:10} "
              f"{count:4} activities   https://{HOST}/pf/{name}/")


def _backfill_internal_port(name: str) -> None:
    """Add PACEFORGE_RUNNER_INTERNAL_PORT to instances provisioned before the
    runner moved its trusted loopback listener onto a second port."""
    env = env_of(name)
    if env.get("PACEFORGE_RUNNER_INTERNAL_PORT") or "PACEFORGE_RUNNER_PORT" not in env:
        return
    f = ENV_DIR / f"{name}.env"
    f.write_text(f.read_text().rstrip("\n")
                 + f"\nPACEFORGE_RUNNER_INTERNAL_PORT={int(env['PACEFORGE_RUNNER_PORT']) + 100}\n")


def cmd_update(args: argparse.Namespace) -> None:
    """Copy the main checkout's code into each instance and restart it.

    Deliberately not `git pull`: the main checkout commits Victor's own training
    data to the same branch, so pulling would drag his data in and conflict with
    the instance's. Copying the code directories keeps each instance's git history
    purely its own athlete's data.
    """
    for name in ([args.name] if args.name else instances()):
        dest = USERS / name
        for rel in CODE_DIRS:
            if (MAIN / rel).exists():
                (dest / rel).parent.mkdir(parents=True, exist_ok=True)
                run(["rsync", "-a", "--delete", f"{MAIN / rel}/", f"{dest / rel}/"])
        _backfill_internal_port(name)
        changed = git_commit(dest, f"code: sync from {MAIN.name} @ "
                                   f"{run(['git', 'rev-parse', '--short', 'HEAD'], cwd=MAIN)}")
        run(["systemctl", "--user", "restart", f"paceforge-runner@{name}"])
        print(f"→ {name}: {'code updated' if changed else 'already current'}, runner restarted")


def cmd_remove(args: argparse.Namespace) -> None:
    name = args.name
    if not NAME_RE.match(name) or name not in instances():
        sys.exit(f"! no instance named {name} (have: {', '.join(instances()) or 'none'})")
    if not args.yes:
        sys.exit(f"! this deletes {USERS / name} and all of {name}'s training data. "
                 "Re-run with --yes.")
    run(["systemctl", "--user", "disable", "--now", *[u.format(n=name) for u in UNITS]],
        check=False)
    caddy_edit(drop=name)
    shutil.rmtree(USERS / name)
    (ENV_DIR / f"{name}.env").unlink(missing_ok=True)
    shutil.rmtree(ENV_DIR / f"garmin-{name}", ignore_errors=True)
    shutil.rmtree(HOME / ".local" / "state" / f"paceforge-{name}", ignore_errors=True)
    print(f"removed {name}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("add", help="provision a new athlete's instance")
    p.add_argument("name", help="lowercase short name, becomes the login + URL")
    p.add_argument("--port", type=int, help="runner port (default: first free from 8124)")
    p.add_argument("--password", help="portal password (default: generated)")
    p.set_defaults(func=cmd_add)

    p = sub.add_parser("list", help="show every instance")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("update", help="pull code from the main checkout and restart")
    p.add_argument("name", nargs="?", help="one instance (default: all)")
    p.set_defaults(func=cmd_update)

    p = sub.add_parser("remove", help="delete an instance and its data")
    p.add_argument("name")
    p.add_argument("--yes", action="store_true", help="confirm the deletion")
    p.set_defaults(func=cmd_remove)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
