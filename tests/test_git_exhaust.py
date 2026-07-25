#!/usr/bin/env python3
"""Git exhaust: unique-commits-observed metadata, end to end against real
git repositories.

    python3 tests/test_git_exhaust.py

Real subprocesses, real git, real worktree gitdirs — only the network is
absent (build_metadata never talks to it). This is the canonical proof for
the plan's kit half: the exhaust must credit the posting author's commits
(never the world's after a pull), survive rebases via the ancestry guard,
emit on the FIRST post of an ephemeral worktree via the merge-base
fallback, and vanish rather than block or guess.
"""
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "skills", "team-room"))
os.environ.setdefault("ROOM_JSON", os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "fixtures", "room.json"))

import room_post as rp  # noqa: E402

AUTHOR = "author@test.local"
TEAMMATE = "teammate@test.local"


def sh(*args, cwd, env_email=None):
    env = dict(os.environ)
    env.update({
        "GIT_AUTHOR_NAME": "t", "GIT_COMMITTER_NAME": "t",
        "GIT_AUTHOR_EMAIL": env_email or AUTHOR,
        "GIT_COMMITTER_EMAIL": env_email or AUTHOR,
    })
    subprocess.run(args, cwd=cwd, env=env, check=True,
                   capture_output=True, text=True)


def commit(repo, name, lines, email=None):
    path = os.path.join(repo, name)
    with open(path, "w") as f:
        f.write("\n".join(f"line {i}" for i in range(lines)) + "\n")
    sh("git", "add", name, cwd=repo)
    sh("git", "commit", "-q", "-m", f"add {name}", cwd=repo, env_email=email)


def make_origin_and_clone():
    """An 'origin' repo with a main branch, cloned — so origin/main exists,
    like every real checkout."""
    root = tempfile.mkdtemp()
    origin = os.path.join(root, "proving-ground")
    os.makedirs(origin)
    sh("git", "init", "-q", "-b", "main", cwd=origin)
    sh("git", "config", "user.email", TEAMMATE, cwd=origin)
    commit(origin, "base.txt", 3, email=TEAMMATE)
    clone = os.path.join(root, "clone")
    sh("git", "clone", "-q", origin, clone, cwd=root)
    sh("git", "config", "user.email", AUTHOR, cwd=clone)
    sh("git", "checkout", "-q", "-b", "feat/x", cwd=clone)
    return origin, clone


def in_dir(d):
    os.chdir(d)
    rp._EXHAUST_TOKEN = None


def test_cold_start_emits_via_merge_base():
    # Most agent sessions are single-post ephemeral worktrees; a silent
    # first post would zero out exactly the sessions the metric exists for.
    _, clone = make_origin_and_clone()
    in_dir(clone)
    commit(clone, "one.txt", 5)
    ex = rp._git_exhaust()
    assert ex["repo"] == "proving-ground", ex
    assert ex["commits"] == 1, ex
    assert len(ex["commit_shas"]) == 1, ex
    assert ex["diff"]["added"] == 5 and ex["diff"]["files"] == 1, ex
    print("PASS  test_cold_start_emits_via_merge_base")


def test_metadata_carries_deduplicatable_commits_since_last_post():
    # The canonical scenario: post, work (while a teammate's commit lands
    # in range), post again. Only the author's two commits count, with
    # their OIDs so downstream dedup by (repo, sha) can collapse overlap.
    _, clone = make_origin_and_clone()
    in_dir(clone)
    commit(clone, "one.txt", 5)
    rp._git_exhaust()
    rp._advance_room_marker()          # the success path does exactly this
    marker = os.path.join(clone, ".git", "room-last-head")
    assert os.path.exists(marker), "marker must exist after advance"

    commit(clone, "two.txt", 7)
    commit(clone, "three.txt", 2)
    commit(clone, "theirs.txt", 100, email=TEAMMATE)  # in range, not ours
    ex = rp._git_exhaust()
    assert ex["commits"] == 2, ex                    # author filter held
    # The OIDs are the dedup key — pin them against git itself, newest first.
    import subprocess as sp
    real = sp.run(["git", "log", "--format=%h", "--author=author@test.local",
                   "-2"], cwd=clone, capture_output=True, text=True,
                  env={**os.environ, "LC_ALL": "C"}).stdout.split()
    assert [s[:len(real[0])] for s in ex["commit_shas"]] == real, (ex, real)
    assert ex["diff"] == {"files": 2, "added": 9, "deleted": 0}, ex
    print("PASS  test_metadata_carries_deduplicatable_commits_since_last_post")


def test_rebase_orphans_marker_and_ancestry_guard_falls_back():
    # A rebased sha stays in the object store, so rev-list on it SUCCEEDS
    # with a garbage range. The ancestry check must reject it and fall back
    # to merge-base — never emit the garbage.
    _, clone = make_origin_and_clone()
    in_dir(clone)
    commit(clone, "one.txt", 5)
    rp._git_exhaust()
    rp._advance_room_marker()
    # Rewrite history: the recorded head is no longer an ancestor.
    sh("git", "reset", "-q", "--hard", "origin/main", cwd=clone)
    commit(clone, "redone.txt", 4)
    ex = rp._git_exhaust()
    assert ex["commits"] == 1, ex          # merge-base window, not garbage
    assert ex["diff"]["added"] == 4, ex
    print("PASS  test_rebase_orphans_marker_and_ancestry_guard_falls_back")


def test_unknown_marker_sha_falls_back_instead_of_omitting():
    # A marker sha git has never seen (say, copied state or a pruned
    # object): without the ancestry guard the rev-list would ERROR and the
    # fields would vanish. The guard must reject it upfront and fall back
    # to merge-base, so the post still carries the branch's work.
    _, clone = make_origin_and_clone()
    in_dir(clone)
    commit(clone, "one.txt", 5)
    with open(os.path.join(clone, ".git", "room-last-head"), "w") as f:
        f.write("deadbeefdeadbeefdeadbeefdeadbeefdeadbeef\n")
    ex = rp._git_exhaust()
    assert ex.get("commits") == 1, ex          # fallback window, not omission
    print("PASS  test_unknown_marker_sha_falls_back_instead_of_omitting")


def test_zero_commits_is_reported_not_dropped():
    # "commits": 0 is coverage data (a post with no new commits) and must
    # survive build_metadata's falsy-filter.
    _, clone = make_origin_and_clone()
    in_dir(clone)
    commit(clone, "one.txt", 5)
    rp._git_exhaust()
    rp._advance_room_marker()
    meta = rp.build_metadata("done", [])
    assert meta.get("commits") == 0, meta
    print("PASS  test_zero_commits_is_reported_not_dropped")


def test_non_git_directory_emits_nothing():
    in_dir(tempfile.mkdtemp())
    ex = rp._git_exhaust()
    assert ex == {}, ex
    print("PASS  test_non_git_directory_emits_nothing")


def test_exhausted_budget_emits_nothing_and_never_blocks():
    _, clone = make_origin_and_clone()
    in_dir(clone)
    import time
    t0 = time.monotonic()
    ex = rp._git_exhaust(budget_seconds=-1)
    took = time.monotonic() - t0
    assert ex == {}, ex     # a spent budget means no calls and no fields
    assert took < 0.5, f"budget-exhausted path took {took:.2f}s"
    print("PASS  test_exhausted_budget_emits_nothing_and_never_blocks")


def test_cumulative_slow_calls_respect_the_deadline():
    # Two 1.8s calls would stack to 3.6s if each only honored its own 2s
    # timeout — the remaining-budget threading must cap the TOTAL. Simulate
    # slow git by wrapping git_rc with a sleep that consumes budget.
    _, clone = make_origin_and_clone()
    in_dir(clone)
    commit(clone, "one.txt", 5)
    import time
    real = rp.git_rc

    def slow(*args, timeout=2.0):
        time.sleep(min(0.25, timeout))
        return real(*args, timeout=timeout)

    rp.git_rc = slow
    try:
        t0 = time.monotonic()
        rp._git_exhaust(budget_seconds=0.6)
        took = time.monotonic() - t0
    finally:
        rp.git_rc = real
    # 8 calls x 0.25s would be 2s unthrottled; the budget must cut it off.
    assert took < 1.6, f"deadline not enforced across calls: {took:.2f}s"
    print("PASS  test_cumulative_slow_calls_respect_the_deadline")


def test_zero_commit_window_omits_diff():
    # commits == 0 must NOT ship a zero-filled diff dict: absent beats
    # filler, and a {0,0,0} diff reads as "measured nothing changed".
    _, clone = make_origin_and_clone()
    in_dir(clone)
    commit(clone, "one.txt", 5)
    rp._git_exhaust()
    rp._advance_room_marker()
    ex = rp._git_exhaust()
    assert ex.get("commits") == 0, ex
    assert "diff" not in ex and "commit_shas" not in ex, ex
    print("PASS  test_zero_commit_window_omits_diff")


def test_marker_lives_in_linked_worktree_gitdir():
    # A linked worktree's marker must land in .git/worktrees/<name>/, so it
    # is per-worktree and dies with the worktree.
    _, clone = make_origin_and_clone()
    wt = clone + "-wt"
    sh("git", "worktree", "add", "-q", "-b", "feat/wt", wt, cwd=clone)
    sh("git", "config", "user.email", AUTHOR, cwd=clone)
    in_dir(wt)
    commit(wt, "wt.txt", 1)
    rp._git_exhaust()
    rp._advance_room_marker()
    expected = os.path.join(clone, ".git", "worktrees",
                            os.path.basename(wt), "room-last-head")
    assert os.path.exists(expected), expected
    assert not os.path.exists(os.path.join(wt, ".git", "room-last-head"))
    print("PASS  test_marker_lives_in_linked_worktree_gitdir")


if __name__ == "__main__":
    test_cold_start_emits_via_merge_base()
    test_metadata_carries_deduplicatable_commits_since_last_post()
    test_rebase_orphans_marker_and_ancestry_guard_falls_back()
    test_unknown_marker_sha_falls_back_instead_of_omitting()
    test_zero_commits_is_reported_not_dropped()
    test_non_git_directory_emits_nothing()
    test_exhausted_budget_emits_nothing_and_never_blocks()
    test_cumulative_slow_calls_respect_the_deadline()
    test_zero_commit_window_omits_diff()
    test_marker_lives_in_linked_worktree_gitdir()
    print("OK")
