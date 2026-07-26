#!/usr/bin/env python3
"""Freshness: can this copy of the kit tell that it is behind?

    python3 tests/test_freshness.py

The integrity check only proves a copy matches what it was INSTALLED from, so
a kit six versions behind reports "ok" forever. That is how a fleet drifts
without anyone noticing. This is the check that can say "behind", and the
properties that matter are as much about SILENCE as about detection: while
the repo is unpublished the check must say nothing at all, or every doctor
run grows a red line nobody should act on, and people learn to skim past
doctor entirely.

No network: the upstream fetch is stubbed at the urlopen boundary.
"""
import io
import os
import sys
import urllib.error

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "skills", "team-room"))
os.environ.setdefault("TEAM_ROOM_TRUST_SERVER", "1")
os.environ.setdefault("ROOM_JSON", os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "fixtures", "room.json"))
os.environ["TEAM_ROOM_HEALTH_LOG"] = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), ".freshness-health.jsonl")

import room_post as rp  # noqa: E402

PASS = FAIL = 0


def check(label, ok):
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"PASS  {label}")
    else:
        FAIL += 1
        print(f"FAIL  {label}")


class _Resp(io.BytesIO):
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def stub_urlopen(payload):
    def _open(req, timeout=None):
        if isinstance(payload, Exception):
            raise payload
        return _Resp(payload)
    return _open


def health_rows():
    try:
        import json
        with open(os.environ["TEAM_ROOM_HEALTH_LOG"]) as fh:
            return [json.loads(l) for l in fh if l.strip()]
    except OSError:
        return []


def reset_health():
    try:
        os.unlink(os.environ["TEAM_ROOM_HEALTH_LOG"])
    except OSError:
        pass


_real = rp.urllib.request.urlopen

# --- the hash identifies content, not filenames or install flavor --------
# room_post.py is byte-identical across every install flavor while SKILL.md
# is rewritten by the repo installer, which is exactly why the script is the
# comparison subject.
check("identical bytes hash identically",
      rp._source_version(b"same") == rp._source_version(b"same"))
check("one changed byte changes the hash",
      rp._source_version(b"same") != rp._source_version(b"sane"))
check("the local hash is derived from this very file",
      rp._local_source_version() == rp._source_version(
          open(os.path.abspath(rp.__file__), "rb").read()))

# --- it can actually tell current from behind ----------------------------
rp.urllib.request.urlopen = stub_urlopen(b"upstream contents")
check("an upstream that differs is reported as a different version",
      rp._upstream_source_version() == rp._source_version(b"upstream contents"))

with open(os.path.abspath(rp.__file__), "rb") as fh:
    mine = fh.read()
rp.urllib.request.urlopen = stub_urlopen(mine)
check("an identical upstream matches the local version exactly",
      rp._upstream_source_version() == rp._local_source_version())

# --- silence while the repo is unpublished -------------------------------
# 404 is the everyday answer today. It is not an incident, and writing it to
# the ledger would put a red line under every doctor run.
reset_health()
rp.urllib.request.urlopen = stub_urlopen(
    urllib.error.HTTPError("u", 404, "Not Found", {}, None))
check("an unpublished repo yields no version", rp._upstream_source_version() is None)
check("an unpublished repo writes nothing to the health ledger",
      not [r for r in health_rows() if r.get("component") == "freshness-check"])

reset_health()
rp.urllib.request.urlopen = stub_urlopen(
    urllib.error.HTTPError("u", 403, "rate limited", {}, None))
check("a rate limit yields no version", rp._upstream_source_version() is None)
check("a rate limit is not logged as an incident either",
      not [r for r in health_rows() if r.get("component") == "freshness-check"])

# --- but a genuine surprise is recorded ----------------------------------
reset_health()
rp.urllib.request.urlopen = stub_urlopen(
    urllib.error.HTTPError("u", 500, "boom", {}, None))
check("a server error yields no version", rp._upstream_source_version() is None)
check("a server error DOES reach the health ledger",
      any(r.get("component") == "freshness-check" for r in health_rows()))

reset_health()
rp.urllib.request.urlopen = stub_urlopen(TimeoutError("timed out"))
check("a timeout yields no version", rp._upstream_source_version() is None)
check("a timeout reaches the health ledger",
      any(r.get("component") == "freshness-check" for r in health_rows()))

# --- the check can never be the reason a command fails -------------------
reset_health()
for boom in (OSError("dns"), ValueError("garbage"), KeyboardInterrupt()):
    rp.urllib.request.urlopen = stub_urlopen(boom)
    try:
        rp._upstream_source_version()
        ok = True
    except BaseException:
        ok = False
    if not ok:
        break
check("no exception escapes the freshness check", ok)

rp.urllib.request.urlopen = _real
reset_health()

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
