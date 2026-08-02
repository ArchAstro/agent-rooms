# Kit sync contract

Two copies of this kit exist on purpose, and this file is the contract
that keeps them honest:

- `ArchAstro/firstlanding` → `.claude/skills/team-room/` — the WORKING
  copy. Kit changes are developed, reviewed, and merged there first (it
  has the richest real exhaust to verify against).
- `ArchAstro/agent-rooms` → `skills/team-room/` — the DISTRIBUTION copy.
  The npx installer and every non-firstlanding repo install from here.

The rule: **a kit change merged in firstlanding is ported here in the
same sitting, and the port is byte-identical** for `room_post.py` and
`evidence/` (tests may adapt their path preamble). Check with:

    diff -r <firstlanding>/.claude/skills/team-room/evidence skills/team-room/evidence
    diff <firstlanding>/.claude/skills/team-room/room_post.py skills/team-room/room_post.py

`KIT_VERSION` inside `room_post.py` is the drift tell: if the two copies
show different versions, the distribution copy is stale and anyone
installing fresh gets old behavior. This exact failure happened on
2026-08-02 (firstlanding shipped 2026.08.02 while this repo sat at
2026.07.25) and was caught by a human asking, not by tooling — hence
this file. A CI cross-check needs read access to the private
firstlanding repo; until someone wires that secret, this contract plus
the version tell is the guard.
