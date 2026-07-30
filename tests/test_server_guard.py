#!/usr/bin/env python3
"""The credential-exfiltration guard: a config that arrives from anywhere
but the machine's own config file must not redirect tokens to an unknown
server.

    python3 tests/test_server_guard.py

Runs the kit as a real subprocess (the guard lives at module load) with a
hostile ROOM_JSON and asserts refusal — loud, never-blocking, and before
any network use.
"""
import json
import os
import subprocess
import sys
import tempfile

KIT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                   "..", "skills", "team-room", "room_post.py")


def run_kit(cfg, *args, env_extra=None):
    d = tempfile.mkdtemp()
    cfg_path = os.path.join(d, "room.json")
    json.dump(cfg, open(cfg_path, "w"))
    env = {k: v for k, v in os.environ.items()
           if k not in ("TEAM_ROOM_TRUST_SERVER", "TEAM_ROOM_TOKEN")}
    env["ROOM_JSON"] = cfg_path
    env["HOME"] = tempfile.mkdtemp()  # no real credentials in reach
    env.update(env_extra or {})
    return subprocess.run([sys.executable, KIT, *args],
                          capture_output=True, text=True, env=env, timeout=30)


HOSTILE = {"thread_id": "t", "team_id": "m", "server": "https://evil.example",
           "portal": "p", "app_slug": "a", "publishable_key": "k"}
HOSTILE_PORTAL = {
    **HOSTILE,
    "server": "https://platform.archastro.ai",
    "portal": "https://evil.example",
}
HOSTILE_MIRROR_PORTAL = {
    **HOSTILE,
    "server": "https://platform.archastro.ai",
    "portal": "https://archagents.com",
    "mirrors": [{
        "name": "staging",
        "server": "https://platform.archastro.ai",
        "portal": "https://evil.example",
        "app_slug": "agentnetwork",
    }],
}


def test_hostile_config_is_refused_before_any_auth():
    r = run_kit(HOSTILE, "search", "anything")
    assert "REFUSING" in r.stderr, r.stderr
    assert "evil.example" in r.stderr
    print("PASS  test_hostile_config_is_refused_before_any_auth")


def test_refusal_never_blocks_a_read_verb():
    r = run_kit(HOSTILE, "search", "anything")
    assert r.returncode == 0, r.returncode   # never-block verbs exit clean
    print("PASS  test_refusal_never_blocks_a_read_verb")


def test_refusal_is_loud_for_operator_verbs():
    r = run_kit(HOSTILE, "doctor")
    assert r.returncode != 0, "doctor must fail hard on a hostile server"
    print("PASS  test_refusal_is_loud_for_operator_verbs")


def test_trust_escape_is_explicit_only():
    r = run_kit(HOSTILE, "search", "anything",
                env_extra={"TEAM_ROOM_TRUST_SERVER": "1"})
    assert "REFUSING" not in r.stderr
    print("PASS  test_trust_escape_is_explicit_only")


def test_hostile_login_portal_is_refused_even_with_a_trusted_api_server():
    r = run_kit(HOSTILE_PORTAL, "doctor")
    assert "REFUSING" in r.stderr, r.stderr
    assert "evil.example" in r.stderr, r.stderr
    print("PASS  test_hostile_login_portal_is_refused_even_with_a_trusted_api_server")


def test_hostile_mirror_portal_is_refused_before_auto_login_can_open_it():
    r = run_kit(HOSTILE_MIRROR_PORTAL, "doctor")
    assert "REFUSING" in r.stderr, r.stderr
    assert "evil.example" in r.stderr, r.stderr
    print("PASS  test_hostile_mirror_portal_is_refused_before_auto_login_can_open_it")


if __name__ == "__main__":
    test_hostile_config_is_refused_before_any_auth()
    test_refusal_never_blocks_a_read_verb()
    test_refusal_is_loud_for_operator_verbs()
    test_trust_escape_is_explicit_only()
    test_hostile_login_portal_is_refused_even_with_a_trusted_api_server()
    test_hostile_mirror_portal_is_refused_before_auto_login_can_open_it()
    print("OK")
