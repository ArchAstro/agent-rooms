#!/usr/bin/env bash
# Canonical boundary proof: running the real installer battery must not rewrite
# the invoking developer's global Git identity.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUTER="$(mktemp -d)"
trap 'rm -rf "$OUTER"' EXIT

cat >"$OUTER/.gitconfig" <<'EOF'
[user]
	name = Human Name
	email = human@example.test
EOF
cp "$OUTER/.gitconfig" "$OUTER/expected.gitconfig"

HOME="$OUTER" bash "$ROOT/tests/installer_battery.sh" >/dev/null

if ! cmp -s "$OUTER/expected.gitconfig" "$OUTER/.gitconfig"; then
  echo "FAIL: installer battery rewrote the invoking global Git config" >&2
  diff -u "$OUTER/expected.gitconfig" "$OUTER/.gitconfig" >&2 || true
  exit 1
fi

echo "PASS installer battery preserves the invoking global Git config"
