#!/usr/bin/env bash
# The installer heal-paths, as a repeatable battery. Every case here was a
# real production failure first: fossil shims executing frozen code, a
# hand-made symlink the installer would have destroyed, broken instruction
# markers it would have corrupted, identity it must not invent.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
S="$(mktemp -d)"
trap 'rm -rf "$S"' EXIT
export GIT_CONFIG_GLOBAL="$S/test-global-gitconfig"
git config --global user.email ci@test || true
git config --global user.name ci || true

fail() { echo "FAIL: $1"; exit 1; }

# Case 1: fossil install with legacy identity migrates and forwards.
mkdir -p "$S/h1/.archastro/team-room" "$S/h1/.local/bin" "$S/h1/.claude"
cp "$ROOT/skills/team-room/room_post.py" "$S/h1/.archastro/team-room/"
printf '{"thread_id":"t","team_id":"m","server":"s","portal":"p","app_slug":"a","publishable_key":"k"}\n' > "$S/h1/.archastro/team-room/room.json"
HOME="$S/h1" node "$ROOT/bin/install.mjs" --machine >/dev/null
grep -q "orwarder" "$S/h1/.archastro/team-room/room_post.py" || fail "legacy not forwarded"
! grep -q "reinstall with" "$S/h1/.archastro/team-room/room_post.py" || fail "legacy forwarder narrates maintenance"
! grep -q "re-run: npx" "$S/h1/.local/bin/room-post" || fail "machine shim narrates fallback maintenance"
[ -f "$S/h1/.config/team-room/room.json" ] || fail "identity not migrated"
[ -f "$S/h1/.claude/skills/team-room/reference.md" ] || fail "reference.md missing from harness skill"
grep -q "does not activate Agent" "$S/h1/.claude/CLAUDE.md" || fail "machine instructions imply activation"
! grep -q "Before starting work" "$S/h1/.claude/CLAUDE.md" || fail "machine capability mandates participation"
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
install_output="$(HOME="$S/h4" node "$ROOT/bin/install.mjs" --machine)"
[ ! -f "$S/h4/.config/team-room/room.json" ] || fail "identity invented"
[ -f "$S/h4/.archastro/agent-rooms/room_post.py" ] || fail "kit not installed"
[[ "$install_output" != *"room-post subscribe"* ]] || fail "installer recommends removed subscribe command"
[[ "$install_output" == *"--repo"* ]] || fail "installer omits the real repository opt-in path"
echo "PASS zero-config install"

# Case 5: upgrades remove the deferred review runtime while every publication
# runtime survives both install modes and imports from the installed copy,
# rather than accidentally importing this checkout.
mkdir -p "$S/h5/.archastro/agent-rooms/evidence/routines"
printf 'stale review runtime\n' >"$S/h5/.archastro/agent-rooms/evidence/review.py"
printf '{}\n' >"$S/h5/.archastro/agent-rooms/evidence/routines/pr-evidence-review.json"
HOME="$S/h5" node "$ROOT/bin/install.mjs" --machine >/dev/null
PYTHONPATH="$S/h5/.archastro/agent-rooms" python3 -c 'import evidence; from evidence.adapters.first_party import FirstPartyAdapter; from evidence.publisher import ArtifactClient; from evidence.schema import __name__; from evidence.summary import trajectory_summary; assert callable(trajectory_summary); assert not hasattr(ArtifactClient, "invoke_routine")' || fail "machine evidence import failed"
[ -f "$S/h5/.archastro/agent-rooms/evidence/schema/pr-evidence-v1.json" ] || fail "machine evidence schema missing"
[ ! -e "$S/h5/.archastro/agent-rooms/evidence/review.py" ] || fail "machine review runtime survived upgrade"
[ ! -e "$S/h5/.archastro/agent-rooms/evidence/routines/pr-evidence-review.json" ] || fail "machine review recipe survived upgrade"
mkdir -p "$S/repo"
git init -q "$S/repo"
git -C "$S/repo" config user.email ci@test
git -C "$S/repo" config user.name ci
touch "$S/repo/README"
git -C "$S/repo" add README
git -C "$S/repo" commit -q -m initial
mkdir -p "$S/repo/.claude/skills/team-room/evidence/routines"
printf 'stale review runtime\n' >"$S/repo/.claude/skills/team-room/evidence/review.py"
printf '{}\n' >"$S/repo/.claude/skills/team-room/evidence/routines/pr-evidence-review.json"
HOME="$S/h5" node "$ROOT/bin/install.mjs" --repo "$S/repo" >/dev/null
PYTHONPATH="$S/repo/.claude/skills/team-room" python3 -c 'import evidence; from evidence.adapters.first_party import FirstPartyAdapter; from evidence.bundle import build_bundle; from evidence.summary import trajectory_summary; assert callable(trajectory_summary)' || fail "repo evidence import failed"
[ -f "$S/repo/.claude/skills/team-room/evidence/schema/pr-evidence-v1.json" ] || fail "repo evidence schema missing"
[ ! -e "$S/repo/.claude/skills/team-room/evidence/review.py" ] || fail "repo review runtime survived upgrade"
[ ! -e "$S/repo/.claude/skills/team-room/evidence/routines/pr-evidence-review.json" ] || fail "repo review recipe survived upgrade"
grep -q "Subagents may read but never post" "$S/repo/AGENTS.md" || fail "repo subagent contract missing"
grep -q "narrated or turned into engineer work" "$S/repo/AGENTS.md" || fail "repo attention contract missing"
grep -q "scripts/room-post pr publish" "$S/repo/.claude/skills/team-room/SKILL.md" || fail "repo shim PR publication missing"
python3 - "$ROOT" "$S/h5/.archastro/agent-rooms" "$S/repo/.claude/skills/team-room" <<'PY' || fail "evidence manifest integrity failed"
import hashlib, json, pathlib, sys
_root, machine, repo = map(pathlib.Path, sys.argv[1:])
for installed in (machine, repo):
    manifest = json.loads((installed / 'manifest.json').read_text())['files']
    assert "evidence/adapters/first_party.py" in manifest, installed
    assert "evidence/review.py" not in manifest, installed
    assert "evidence/routines/pr-evidence-review.json" not in manifest, installed
    for rel, expected in manifest.items():
        assert hashlib.sha256((installed / rel).read_bytes()).hexdigest() == manifest[rel], (installed, rel)
PY
echo "PASS evidence install integrity"

# Case 6: the publish-only package output includes every installed runtime and
# cannot reintroduce the deferred review implementation through npm packaging.
python3 - "$ROOT" <<'PY' || fail "package output contract failed"
import json
import pathlib
import subprocess
import sys

root = pathlib.Path(sys.argv[1])
result = subprocess.run(
    ["npm", "pack", "--dry-run", "--json", "--ignore-scripts"],
    cwd=root,
    check=True,
    capture_output=True,
    text=True,
)
packed = {entry["path"] for entry in json.loads(result.stdout)[0]["files"]}
required = {
    "skills/team-room/evidence/adapters/first_party.py",
    "skills/team-room/evidence/publisher.py",
    "skills/team-room/evidence/schema/pr-evidence-v1.json",
}
forbidden = {
    "skills/team-room/evidence/review.py",
    "skills/team-room/evidence/routines/pr-evidence-review.json",
}
assert required <= packed, required - packed
assert packed.isdisjoint(forbidden), packed & forbidden
assert not any("__pycache__" in path or path.endswith(".pyc") for path in packed)
PY
echo "PASS publish-only package output"

# Case 7: an established multi-harness repo keeps every harness's own
# instructions while each always-loaded identity receives exactly one managed
# Room contract. Real customer repositories already have these files; relying
# on symlinks only works for empty demos.
mkdir -p "$S/repo-identities"
git init -q "$S/repo-identities"
git -C "$S/repo-identities" config user.email ci@test
git -C "$S/repo-identities" config user.name ci
printf 'shared agent rules\n' >"$S/repo-identities/AGENTS.md"
printf 'claude-specific rules\n' >"$S/repo-identities/CLAUDE.md"
printf 'gemini-specific rules\n' >"$S/repo-identities/GEMINI.md"
git -C "$S/repo-identities" add AGENTS.md CLAUDE.md GEMINI.md
git -C "$S/repo-identities" commit -q -m initial
HOME="$S/h5" node "$ROOT/bin/install.mjs" --repo "$S/repo-identities" >/dev/null
python3 - "$S/repo-identities" <<'PY' || fail "existing harness identities were not activated"
import pathlib
import sys

repo = pathlib.Path(sys.argv[1])
expected = {
    "AGENTS.md": "shared agent rules",
    "CLAUDE.md": "claude-specific rules",
    "GEMINI.md": "gemini-specific rules",
}
for name, customer_text in expected.items():
    path = repo / name
    assert not path.is_symlink(), (name, "customer identity replaced by symlink")
    text = path.read_text()
    assert customer_text in text, (name, "customer instructions lost")
    assert text.count("<!-- agent-rooms:start -->") == 1, (name, "missing or duplicate start marker")
    assert text.count("<!-- agent-rooms:end -->") == 1, (name, "missing or duplicate end marker")
PY
echo "PASS existing harness identities activated"

# Case 8: identity symlinks stay inside the repository's trust boundary. An
# internal dangling link can be completed safely; an external customer link is
# preserved without rewriting its target outside the install root.
mkdir -p "$S/repo-symlinks/docs"
git init -q "$S/repo-symlinks"
git -C "$S/repo-symlinks" config user.email ci@test
git -C "$S/repo-symlinks" config user.name ci
printf 'shared rules\n' >"$S/repo-symlinks/AGENTS.md"
printf 'external claude rules\n' >"$S/external-claude.md"
ln -s "$S/external-claude.md" "$S/repo-symlinks/docs/claude.md"
ln -s "docs/claude.md" "$S/repo-symlinks/CLAUDE.md"
ln -s "docs/gemini.md" "$S/repo-symlinks/GEMINI.md"
git -C "$S/repo-symlinks" add AGENTS.md CLAUDE.md GEMINI.md
git -C "$S/repo-symlinks" commit -q -m initial
symlink_output="$(HOME="$S/h5" node "$ROOT/bin/install.mjs" --repo "$S/repo-symlinks" 2>&1)"
[ "$(cat "$S/external-claude.md")" = "external claude rules" ] || fail "external identity symlink target was modified"
[ -L "$S/repo-symlinks/CLAUDE.md" ] || fail "external identity symlink was replaced"
[[ "$symlink_output" == *"outside the repository"* ]] || fail "external identity symlink was skipped silently"
[ -L "$S/repo-symlinks/GEMINI.md" ] || fail "internal identity symlink was replaced"
grep -q '<!-- agent-rooms:start -->' "$S/repo-symlinks/docs/gemini.md" || fail "internal dangling identity symlink was not activated"
echo "PASS identity symlink boundary"

echo "installer battery: all green"
