#!/usr/bin/env python3
"""Protocol compliance eval: do real coding agents, given only SKILL.md,
actually behave — search first, read when flagged, post well-shaped exhaust?

    python3 evals/protocol_eval.py [codex|agy|all]

Each scenario hands an agent the skill plus a situation and mechanically
scores the reply. This is the formalization of the A/B pressure tests that
drove the skill rewrite; run it after ANY skill or kit change that could
move behavior. Scores print per scenario; exit 1 if any agent fails a MUST.
"""
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = open(os.path.join(HERE, "..", "skills", "team-room", "SKILL.md")).read()

SCENARIOS = [
    {
        "name": "search-before-anything",
        "must": True,
        "prompt": (
            "You are a NEW member of this team as of today: you have never "
            "seen this codebase and know nothing about its history — disregard "
            "any prior knowledge you think you have about it. Your task from "
            'your human: "the payments reconciler is doing something weird, fix it". '
            "You have NO other information — no error, no file, no failing test.\n"
            "Reply with ONLY your first tool invocation, exactly as you would run it."
        ),
        # A tool-executing agent may RUN the search instead of describing
        # it — result glyphs in the output are stronger evidence than the
        # command string.
        "score": lambda out: (bool(re.search(r"room-post\s+search", out))
                              or bool(re.search(r"(⚠ lesson ·|✓ done ·|→ handoff ·|--- msg_)", out)))
        and not re.search(r"\b(grep|rg|cat|ls|find|git log)\b[^\n]*\n[^\n]*room-post", out),
        "label": "first move is room-post search",
    },
    {
        "name": "read-when-flagged",
        "must": True,
        "prompt": (
            "Mid-task, your human says: 'someone flagged a bug about your feature "
            "in the team room earlier'. Reply with ONLY the next command you run."
        ),
        "score": lambda out: bool(re.search(r"room-post\s+(read|search|inbox)", out)),
        "label": "reads the room before continuing",
    },
    {
        "name": "post-shape",
        "must": True,
        "prompt": (
            "You just spent 40 minutes discovering that the platform's task API "
            "returns 500 on every write until `mix event_store.setup` is run, "
            "because a fresh worktree database lacks the EventStore schema "
            "(error: relation public.streams does not exist). You fixed it and "
            "your PR is #4321. Reply with ONLY the exact room-post command you "
            "run now, nothing else."
        ),
        "score": lambda out: (
            re.search(r"room-post\s+lesson", out)
            and "-b" in out
            and re.search(r"event_store\.setup|public\.streams", out)
            and re.search(r"-r\s+.?#?4321", out)
        ),
        "label": "lesson verb + concrete artifact bullets + ref",
    },
    {
        "name": "no-status-spam",
        "must": False,
        "prompt": (
            "You just renamed a variable in one file, a 30-second change nobody "
            "else depends on. Do you post to the room? Reply YES or NO with one sentence."
        ),
        "score": lambda out: out.strip().upper().startswith("NO"),
        "label": "does not spam trivia",
    },
    {
        "name": "pre-commit-read",
        "must": True,
        "prompt": (
            "You have been heads-down for three hours implementing a feature and "
            "are now about to run git commit and open a PR. Reply with ONLY the "
            "command you run FIRST, before committing."
        ),
        "score": lambda out: bool(re.search(r"room-post\s+(read|search|inbox)", out))
        or bool(re.search(r"(⚠ lesson ·|✓ done ·|→ handoff ·|--- msg_)", out)),
        "label": "reads the room before commit/PR",
    },
    {
        "name": "credit-the-room",
        "must": True,
        "prompt": (
            "You searched the room for your failing deploy and it returned a "
            "teammate's lesson that exactly explains the failure (a stale "
            "CDN config that must be purged first). What do you say to your "
            "human BEFORE applying the fix? Reply with that one sentence."
        ),
        "score": lambda out: bool(re.search(r"\b(room|teammate)\b", out, re.I))
        and bool(re.search(r"(found|already|knew|knows|flagged|documented|paid)", out, re.I)),
        "label": "says the room found it, credits the source",
    },
    {
        "name": "subagent-discipline",
        "must": True,
        "prompt": (
            "You are a SUBAGENT spawned by a parent session to investigate flaky "
            "billing tests. You just discovered the root cause: a shared sandbox "
            "port collision. Do you post this to the team room yourself? Reply "
            "YES or NO with one sentence."
        ),
        "score": lambda out: out.strip().upper().startswith("NO"),
        "label": "subagent returns findings, never posts",
    },
    {
        "name": "contradiction-search",
        "must": True,
        "prompt": (
            "A reviewer says your change breaks the billing tests. Your tests pass "
            "locally and you believe the reviewer is wrong. Reply with ONLY the "
            "next command you run."
        ),
        "score": lambda out: bool(re.search(r"room-post\s+search", out)),
        "label": "searches before arguing",
    },
]


def ask(agent, prompt):
    full = f"The following skill governs how you work:\n\n{SKILL}\n\n---\n{prompt}"
    if agent == "codex":
        cmd = ["codex", "exec", "--skip-git-repo-check", full]
    else:
        cmd = ["agy", "--effort", "low", "-p", full]
    # Sandbox ONLY the room, never HOME: overriding HOME hides every other
    # tool's credentials too (a real agy relaunched a Google login mid-eval
    # and popped a browser at the operator). An invalid static room token
    # makes any executed room-post 401 and fail soft — nothing can land.
    env = dict(os.environ)
    env["TEAM_ROOM_TOKEN"] = "eval-sandbox-invalid-token"
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=240,
                       stdin=subprocess.DEVNULL, env=env)
    return (r.stdout or "") + (r.stderr or "")


def main():
    targets = sys.argv[1:] or ["codex", "agy"]
    if targets == ["all"]:
        targets = ["codex", "agy"]
    hard_fail = False
    for agent in targets:
        print(f"\n=== {agent} ===")
        for sc in SCENARIOS:
            try:
                out = ask(agent, sc["prompt"])
                ok = bool(sc["score"](out))
            except Exception as exc:
                ok, out = False, f"(runner error: {exc})"
            tag = "PASS" if ok else ("FAIL" if sc["must"] else "warn")
            if not ok and sc["must"]:
                hard_fail = True
            print(f"{tag:5} {sc['name']:24} {sc['label']}")
            if not ok:
                tail = " | ".join(out.strip().splitlines()[-3:])[:200]
                print(f"      last output: {tail}")
    sys.exit(1 if hard_fail else 0)


if __name__ == "__main__":
    main()
