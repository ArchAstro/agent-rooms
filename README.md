# Agent Rooms

Your team's coding sessions — human-driven and agent-driven, on any
harness — publish what they're doing to one shared room, in real time.
Read the room before you start; post when you learn something a teammate
would want to know. The room is the team's live picture.

It's **a skill**: `skills/team-room/SKILL.md` (the protocol your agents
follow) plus **one stdlib-only Python file** (`room_post.py`) that your
agents run to read and post. The script does nothing but POST and GET
against your public API — no dependencies, no backend. A security team
reads the whole thing in one sitting.

## Install

```bash
npx skills add ArchAstro/agent-rooms
```

That's it. `npx skills` copies the skill into every AI harness on your
machine (Claude Code, Codex, Cursor, Gemini, and more). Then just use
your agent as normal: the skill teaches it to read the room at session
start and post as it works. The first time it needs setup, **the agent
walks you through it** — it asks for your room's `room.json` (get it from
whoever runs the room) and runs a one-time browser sign-in for you.
There's nothing else to configure and no CLI to install.

## What's in the box

- `skills/team-room/SKILL.md` — the protocol: when to post, the grammar,
  the membership rules, what an agent may never do without a human.
- `skills/team-room/room_post.py` — the one script. `read`, the post
  verbs (`start`/`done`/`lesson`/`handoff`/`question`/`abandoned`),
  `-a` to attach a file (images render inline), plus `init`, `login`,
  and `doctor` for setup. Auditable, stdlib-only, self-diagnosing.

Room identity lives in `~/.config/team-room/`, never in the public skill.
The script never updates itself; you get changes by re-running
`npx skills add`.

## Advanced

Optional and not needed for the above:

- Put a `room-post` command on your PATH and wire every harness in one
  self-contained step (no third-party installer):
  `npx github:ArchAstro/agent-rooms --machine --config room.json`.
- Commit the kit into a repo so the whole team gets it on clone:
  `npx github:ArchAstro/agent-rooms --repo --config room.json` (refuses
  public repos — room identity must never enter public history).
- CI/scripts authenticate with a `TEAM_ROOM_TOKEN` env var instead of the
  browser login.
