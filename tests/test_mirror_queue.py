#!/usr/bin/env python3
"""Mirror copies deliver from a queue, not from a 1-second inline prayer.

    python3 .claude/skills/team-room/tests/test_mirror_queue.py

Stdlib only, no network, no pytest. The properties under test, in the
order they were earned:

- posting NEVER waits on a mirror: fan-out appends one self-describing
  line and (at most) spawns one worker;
- each entry records its OWN targets and a stable idempotency key, so a
  worker running under a different room config can never deliver a post
  to the wrong room, and a retry after an ambiguous outcome upserts
  instead of duplicating (review finds);
- the worker delivers per target IN ORDER with real timeouts; a failing
  tier keeps its backlog without blocking healthy tiers; week-old
  entries expire with a health line;
- one flusher at a time, and the spawn-probe pairs with the worker's
  drain-then-recheck loop so an entry appended mid-drain is never
  stranded (the lost-wakeup review find).
"""
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
KIT = os.path.join(HERE, "..", "skills", "team-room")
sys.path.insert(0, KIT)
os.environ.setdefault("TEAM_ROOM_TRUST_SERVER", "1")
os.environ.setdefault("ROOM_JSON", os.path.join(HERE, "fixtures", "room.json"))

import room_post as rp  # noqa: E402


def check(name, ok, detail=""):
    print(f"{'PASS' if ok else 'FAIL'}  {name}{('  , ' + detail) if detail else ''}")
    return ok


class Recorder:
    def __init__(self):
        self.calls = []  # (server, thread, content, idempotency_key)
        self.health = []
        self.spawned = 0


def fresh(rec: Recorder, fail_servers=()):
    """Point the module at a temp queue and fake every boundary."""
    tmp = tempfile.mkdtemp()
    rp.MIRROR_QUEUE_PATH = os.path.join(tmp, "mirror-queue.jsonl")
    rp.MIRRORS = [
        {"name": "staging", "server": "https://s", "portal": "https://p",
         "app_slug": "x", "thread_id": "thr_S"},
        {"name": "latest", "server": "https://l", "portal": "https://p",
         "app_slug": "x", "thread_id": "thr_L"},
    ]
    rp.MIRROR_FLUSH_TOTAL_BUDGET_SECONDS = 10.0
    rp._trusted_servers = lambda: {"https://s", "https://l"}
    rp._mirror_session = lambda m, timeout: {
        "accessToken": "t", "appId": "app", "userId": "usr"}
    def http_json(url, body, token=None, timeout=None):
        server = url.split("/protected/")[0]
        thread = url.rsplit("/", 2)[-2]
        if server in fail_servers:
            raise TimeoutError("slow tier")
        rec.calls.append((server, thread, body["content"],
                          body.get("idempotency_key")))
        return {}
    rp.http_json = http_json
    rp.health_event = lambda c, r: rec.health.append((c, r))
    def popen(argv, **k):
        rec.spawned += 1
        return None
    rp.subprocess.Popen = popen
    return tmp


def queue_lines():
    try:
        return [json.loads(l) for l in open(rp.MIRROR_QUEUE_PATH)
                if l.strip()]
    except OSError:
        return []


def test_posting_only_appends_and_spawns_at_most_one_worker():
    rec = Recorder()
    fresh(rec)
    rp.mirror_fanout("hello room", {"post_type": "done"})
    rp.mirror_fanout("second post", None)
    lines = queue_lines()
    mode = os.stat(rp.MIRROR_QUEUE_PATH).st_mode & 0o777
    return (
        check("posting appends self-describing entries, nothing inline",
              len(lines) == 2 and rec.calls == []
              and lines[0]["message"] == "hello room"
              and {t["name"] for t in lines[0]["targets"]} == {"staging", "latest"}
              and len(lines[0]["key"]) == 32)
        and check("the queue file is private to the user", mode == 0o600)
        and check("an idle-lock probe spawns a worker per post at most",
                  rec.spawned == 2)
    )


def test_flush_delivers_in_order_with_idempotency_keys_and_drains():
    rec = Recorder()
    fresh(rec)
    rp.mirror_fanout("first", None)
    rp.mirror_fanout("second", None)
    keys = [l["key"] for l in queue_lines()]
    rp.mirror_flush()
    staging = [c for s, t, c, k in rec.calls if s == "https://s"]
    ks = [k for s, t, c, k in rec.calls if s == "https://s"]
    return (
        check("every target receives every post, oldest first",
              staging == ["first", "second"]
              and [c for s, t, c, k in rec.calls if s == "https://l"] == ["first", "second"])
        and check("each delivery carries the entry's stable idempotency key",
                  ks == [f"mirror-{keys[0]}-staging", f"mirror-{keys[1]}-staging"])
        and check("a drained queue is empty", queue_lines() == [])
    )


def test_entries_deliver_to_their_recorded_targets_not_the_worker_config():
    rec = Recorder()
    fresh(rec)
    rp.mirror_fanout("scoped post", None)
    # The worker wakes up under a DIFFERENT room config (other repo, other
    # room). The entry's recorded targets must win — this is the cross-room
    # leakage guard.
    rp.MIRRORS = [{"name": "other", "server": "https://evil", "portal": "p",
                   "app_slug": "x", "thread_id": "thr_OTHER"}]
    rp.mirror_flush()
    return (
        check("delivery goes to the targets recorded at post time",
              {(s, t) for s, t, c, k in rec.calls}
              == {("https://s", "thr_S"), ("https://l", "thr_L")})
    )


def test_an_untrusted_recorded_server_is_refused():
    rec = Recorder()
    fresh(rec)
    rp.mirror_fanout("tampered", None)
    lines = open(rp.MIRROR_QUEUE_PATH).read().splitlines()
    entry = json.loads(lines[0])
    entry["targets"] = [{"name": "rogue", "server": "https://attacker",
                         "thread_id": "thr_X"}]
    open(rp.MIRROR_QUEUE_PATH, "w").write(json.dumps(entry) + "\n")
    rp.mirror_flush()
    return (
        check("a tampered target server is never contacted",
              rec.calls == []
              and any(c == "mirror:rogue" and "untrusted" in r
                      for c, r in rec.health))
    )


def test_a_failing_tier_keeps_its_backlog_without_blocking_the_healthy_one():
    rec = Recorder()
    fresh(rec, fail_servers={"https://s"})
    rp.mirror_fanout("first", None)
    rp.mirror_fanout("second", None)
    rp.mirror_flush()
    lines = queue_lines()
    return (
        check("the healthy tier drained both posts",
              [c for s, t, c, k in rec.calls if s == "https://l"] == ["first", "second"])
        and check("the failing tier's backlog stays queued, in order",
                  [l["message"] for l in lines] == ["first", "second"]
                  and all(l["done"] == ["latest"] for l in lines))
        and check("the failure left a health line, not an error",
                  any(c == "mirror:staging" for c, _ in rec.health))
    )


def test_week_old_entries_expire_with_a_health_line():
    rec = Recorder()
    fresh(rec, fail_servers={"https://s", "https://l"})
    rp.mirror_fanout("ancient", None)
    lines = open(rp.MIRROR_QUEUE_PATH).read().splitlines()
    entry = json.loads(lines[0])
    entry["at"] -= 8 * 86400
    open(rp.MIRROR_QUEUE_PATH, "w").write(json.dumps(entry) + "\n")
    rp.mirror_flush()
    return (
        check("an expired entry is dropped without delivery",
              queue_lines() == [] and rec.calls == [])
        and check("expiry is recorded",
                  ("mirror-queue", "expired undelivered") in rec.health)
    )


def test_lost_wakeup_is_closed_by_the_recheck_loop():
    rec = Recorder()
    fresh(rec)
    # A poster appends WHILE the worker is draining: the worker's re-read
    # after releasing the lock must pick the new entry up in the same run.
    original_deliver = rp._deliver_to_target
    def deliver_and_sneak(target, entry, sessions, remaining):
        if entry["message"] == "first" and not any(
            l["message"] == "sneaked" for l in queue_lines()
        ):
            rp.mirror_fanout("sneaked", None)
        return original_deliver(target, entry, sessions, remaining)
    rp._deliver_to_target = deliver_and_sneak
    try:
        rp.mirror_fanout("first", None)
        rp.mirror_flush()
    finally:
        rp._deliver_to_target = original_deliver
    return (
        check("an entry appended mid-drain is delivered in the same run",
              "sneaked" in [c for s, t, c, k in rec.calls]
              and queue_lines() == [])
    )


def test_a_second_flusher_exits_while_one_holds_the_lock():
    import fcntl

    rec = Recorder()
    fresh(rec)
    rp.mirror_fanout("held", None)
    lock = open(rp.MIRROR_QUEUE_PATH + ".lock", "w")
    fcntl.flock(lock, fcntl.LOCK_EX)
    rp.mirror_flush()
    fcntl.flock(lock, fcntl.LOCK_UN)
    return (
        check("a concurrent flusher delivers nothing and exits",
              rec.calls == [] and len(queue_lines()) == 1)
    )


if __name__ == "__main__":
    results = [
        test_posting_only_appends_and_spawns_at_most_one_worker(),
        test_flush_delivers_in_order_with_idempotency_keys_and_drains(),
        test_entries_deliver_to_their_recorded_targets_not_the_worker_config(),
        test_an_untrusted_recorded_server_is_refused(),
        test_a_failing_tier_keeps_its_backlog_without_blocking_the_healthy_one(),
        test_week_old_entries_expire_with_a_health_line(),
        test_lost_wakeup_is_closed_by_the_recheck_loop(),
        test_a_second_flusher_exits_while_one_holds_the_lock(),
    ]
    print(f"\n{sum(results)}/{len(results)} passed")
    sys.exit(0 if all(results) else 1)
