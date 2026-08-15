"""scripts/users.py provisions per-athlete instances with zero prior coverage.

NAME_RE feeds straight into a systemd unit name, a URL path and a Caddyfile
block — validate it thoroughly, injection-adjacent edge cases included. The
Caddyfile add/remove logic hand-edits a live production file with regex; a
bug there corrupts routing for every athlete, not just the one being
added/removed.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import users  # noqa: E402

# ── NAME_RE ──────────────────────────────────────────────────────────────────

VALID_NAMES = ["al", "alice", "bob2", "a1b2c3", "user-name", "a" * 21]
INVALID_NAMES = [
    "",
    "a",                # below the 2-char minimum
    "a" * 22,           # above the 21-char maximum
    "Alice",            # uppercase
    "1alice",           # must start with a letter
    "-alice",           # must start with a letter, not a dash
    "alice bob",        # space
    "alice_bob",        # underscore
    "alice/etc",        # path separator — lands in a URL path and a file path
    "alice\n",          # trailing newline — Python's bare $ matches before one
    "alice\r\n",
    "alice.pf",         # dot — could confuse a systemd unit / URL segment
]


@pytest.mark.parametrize("name", VALID_NAMES)
def test_name_re_accepts_valid_names(name):
    assert users.NAME_RE.match(name)


@pytest.mark.parametrize("name", INVALID_NAMES)
def test_name_re_rejects_invalid_names(name):
    assert not users.NAME_RE.match(name)


# ── provisioning a new instance ─────────────────────────────────────────────

def git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True,  # noqa: S603, S607
                          text=True, check=True).stdout.strip()


@pytest.fixture()
def fake_main(tmp_path, monkeypatch):
    """A stand-in main checkout: code, plus athlete data committed to its history."""
    main = tmp_path / "main"
    for rel, body in [("web/index.html", "<html>"),
                      ("scripts/runner.py", "# runner"),
                      ("ops/paceforge-runner@.service", "[Unit]"),
                      (".claude/skills/coach/SKILL.md", "# coach"),
                      ("data/bike/workouts/index.json", "[]"),
                      ("data/profile.json", '{"name": "Victor"}'),
                      (".gitignore", "data/profile.json\n")]:
        p = main / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body)
    git(main.parent, "init", "--quiet", "-b", "master", str(main))
    # -f because .gitignore lists profile.json: it is ignored-but-tracked in the
    # real checkout, which is exactly how it reached a clone's history.
    git(main, "add", "-Af")
    git(main, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "init")
    monkeypatch.setattr(users, "MAIN", main)
    return main


# ── Caddyfile edit/removal ──────────────────────────────────────────────────

ANCHOR = "\thandle_path /paceforge* {\n\t\treverse_proxy 127.0.0.1:8123\n\t}\n"


@pytest.fixture()
def caddy(monkeypatch):
    """Stand in for the real sudo-gated Caddyfile read/write/reload."""
    state = SimpleNamespace(text="", written=None, run_calls=[])

    monkeypatch.setattr(users, "sudo_read", lambda path: state.text)

    def fake_run(cmd, cwd=None, check=True):
        state.run_calls.append(cmd)
        return ""

    monkeypatch.setattr(users, "run", fake_run)

    def fake_subprocess_run(cmd, input=None, text=None, check=None, stdout=None):
        state.written = input
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(users.subprocess, "run", fake_subprocess_run)
    return state


def test_add_inserts_the_new_block_right_after_the_shared_anchor(caddy):
    caddy.text = f"example.com {{\n{ANCHOR}}}\n"
    block = users.caddy_block("alice", 8124)

    users.caddy_edit(add=block)

    assert caddy.written == f"example.com {{\n{ANCHOR}\n{block}}}\n"


def test_add_without_the_anchor_exits_instead_of_writing_a_guess(caddy):
    caddy.text = "example.com {\n}\n"  # no /paceforge block to anchor on

    with pytest.raises(SystemExit):
        users.caddy_edit(add=users.caddy_block("alice", 8124))

    assert caddy.written is None


def test_drop_removes_only_the_named_users_block(caddy):
    alice, bob = users.caddy_block("alice", 8124), users.caddy_block("bob", 8125)
    caddy.text = f"example.com {{\n{ANCHOR}\n{alice}\n{bob}}}\n"

    users.caddy_edit(drop="alice")

    assert "paceforge-user:alice" not in caddy.written
    assert caddy.written.count("paceforge-user:bob") == 1
    assert "reverse_proxy 127.0.0.1:8125" in caddy.written


def test_drop_for_an_absent_name_is_a_no_op_that_writes_nothing(caddy):
    caddy.text = f"example.com {{\n{ANCHOR}}}\n"

    users.caddy_edit(drop="ghost")

    assert caddy.written is None


def test_provisioning_never_carries_the_main_checkouts_history(fake_main, tmp_path):
    # The bug this guards: `add` used to clone MAIN and delete the data in a second
    # commit, so `git show <root>:data/profile.json` still returned Victor's health
    # data in every friend's checkout.
    dest = tmp_path / "alice"
    users.init_instance_repo(dest, "alice")

    assert git(dest, "log", "--all", "--oneline", "--", "data/profile.json") == ""
    assert git(dest, "rev-list", "--count", "HEAD") == "1"


def test_provisioning_leaves_no_remote_to_push_an_athletes_data_to(fake_main, tmp_path):
    dest = tmp_path / "alice"
    users.init_instance_repo(dest, "alice")

    assert git(dest, "remote") == ""


def test_provisioning_copies_the_code_but_none_of_the_athlete_data(fake_main, tmp_path):
    dest = tmp_path / "alice"
    users.init_instance_repo(dest, "alice")

    tracked = git(dest, "ls-files").splitlines()
    assert [t for t in tracked if t.startswith("data/")] == ["data/bike/workouts/index.json"]
    assert "scripts/runner.py" in tracked


def test_provisioning_copies_the_gitignores_sensitive_data_block(fake_main, tmp_path):
    dest = tmp_path / "alice"
    users.init_instance_repo(dest, "alice")

    assert "data/profile.json" in (dest / ".gitignore").read_text()


def test_drop_with_a_truncated_block_fails_safe_instead_of_eating_the_next_block(caddy):
    # alice's block is missing its own closing brace (a hand-edit gone wrong) —
    # the old pattern kept scanning past it and deleted bob's entire block too.
    malformed_alice = ("\t# paceforge-user:alice\n"
                       "\thandle_path /pf/alice* {\n"
                       "\t\treverse_proxy 127.0.0.1:8124\n")
    bob = users.caddy_block("bob", 8125)
    caddy.text = f"example.com {{\n{malformed_alice}{bob}}}\n"

    users.caddy_edit(drop="alice")

    assert caddy.written is None   # no match found — refuses to guess, writes nothing
