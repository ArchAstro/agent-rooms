#!/usr/bin/env bash
# The installer heal-paths, as a repeatable battery. Every case here was a
# real production failure first: fossil shims executing frozen code, a
# hand-made symlink the installer would have destroyed, broken instruction
# markers it would have corrupted, identity it must not invent.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
S="$(mktemp -d)"
git config --global user.email ci@test || true
git config --global user.name ci || true

fail() { echo "FAIL: $1"; exit 1; }

# Case 1: fossil install with legacy identity migrates and forwards.
mkdir -p "$S/h1/.archastro/team-room" "$S/h1/.local/bin" "$S/h1/.claude"
cp "$ROOT/skills/team-room/room_post.py" "$S/h1/.archastro/team-room/"
printf '{"thread_id":"t","team_id":"m","server":"s","portal":"p","app_slug":"a","publishable_key":"k"}\n' > "$S/h1/.archastro/team-room/room.json"
HOME="$S/h1" node "$ROOT/bin/install.mjs" --machine >/dev/null
grep -q "orwarder" "$S/h1/.archastro/team-room/room_post.py" || fail "legacy not forwarded"
[ -f "$S/h1/.config/team-room/room.json" ] || fail "identity not migrated"
[ -f "$S/h1/.claude/skills/team-room/reference.md" ] || fail "reference.md missing from harness skill"
echo "PASS fossil heal"

# Case 2: hand-healed symlink survives; kit is not overwritten.
mkdir -p "$S/h2/.archastro/agent-rooms" "$S/h2/.archastro/team-room"
cp "$ROOT/skills/team-room/room_post.py" "$S/h2/.archastro/agent-rooms/"
ln -s ../agent-rooms/room_post.py "$S/h2/.archastro/team-room/room_post.py"
HOME="$S/h2" node "$ROOT/bin/install.mjs" --machine >/dev/null
[ -L "$S/h2/.archastro/team-room/room_post.py" ] || fail "healed symlink replaced"
grep -q "room-post" "$S/h2/.archastro/agent-rooms/room_post.py" || fail "kit clobbered"
echo "PASS symlink preserved"

# Case 3: broken instruction markers are refused, never corrupted.
mkdir -p "$S/h3/.claude"
printf 'mine\n<!-- agent-rooms:end -->\nstale\n<!-- agent-rooms:start -->\nmore\n' > "$S/h3/.claude/CLAUDE.md"
cp "$S/h3/.claude/CLAUDE.md" "$S/before"
HOME="$S/h3" node "$ROOT/bin/install.mjs" --machine >/dev/null 2>&1
cmp -s "$S/before" "$S/h3/.claude/CLAUDE.md" || fail "broken markers were modified"
echo "PASS marker guard"

# Case 4: no identity anywhere -> install succeeds, no room.json invented.
mkdir -p "$S/h4"
HOME="$S/h4" node "$ROOT/bin/install.mjs" --machine >/dev/null
[ ! -f "$S/h4/.config/team-room/room.json" ] || fail "identity invented"
[ -f "$S/h4/.archastro/agent-rooms/room_post.py" ] || fail "kit not installed"
echo "PASS zero-config install"

echo "installer battery: all green"
