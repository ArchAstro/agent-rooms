#!/usr/bin/env bash
# Vendor the ArchAstroPlatform Swift SDK into Vendor/archastro-swift.
#
# Temporary setup until archastro-swift is published (SPM registry / tagged
# git releases) — then the Xcode project switches to a versioned package
# dependency and Vendor/ goes away.
#
# Usage:
#   ./scripts/vendor_sdk.sh [path-to-archastro-swift-checkout]   # default ../../archastro-swift

set -euo pipefail
cd "$(dirname "$0")/.."

SRC="${1:-../../archastro-swift}"
DEST="Vendor/archastro-swift"

if [[ ! -d "$SRC/Sources/ArchAstroPlatform" ]]; then
  echo "archastro-swift checkout not found at $SRC" >&2
  exit 1
fi

rm -rf "$DEST"
mkdir -p "$DEST"

# Library sources only — the SDK's contract tests, spec snapshot, and node
# tooling stay in the SDK repo.
rsync -a "$SRC/Sources/" "$DEST/Sources/"

# Trimmed manifest: just the library product (the SDK repo's manifest also
# declares test targets whose paths aren't vendored).
cat > "$DEST/Package.swift" <<'EOF'
// swift-tools-version: 6.0
// Vendored manifest — see scripts/vendor_sdk.sh. Library target only.
import PackageDescription

let package = Package(
    name: "archastro-swift",
    platforms: [
        .macOS(.v13),
        .iOS(.v16),
        .tvOS(.v16),
        .watchOS(.v9),
    ],
    products: [
        .library(name: "ArchAstroPlatform", targets: ["ArchAstroPlatform"])
    ],
    targets: [
        .target(
            name: "ArchAstroPlatform",
            path: "Sources/ArchAstroPlatform"
        )
    ]
)
EOF

# Record provenance.
SHA="$(git -C "$SRC" rev-parse HEAD 2>/dev/null || echo unknown)"
BRANCH="$(git -C "$SRC" rev-parse --abbrev-ref HEAD 2>/dev/null || echo unknown)"
cat > "$DEST/VENDORED.md" <<EOF
# Vendored ArchAstroPlatform SDK

- Source: https://github.com/ArchAstro/archastro-swift
- Commit: $SHA ($BRANCH)
- Vendored: $(date -u +"%Y-%m-%dT%H:%M:%SZ")

Do not edit files here — refresh with \`./scripts/vendor_sdk.sh\`.
EOF

echo "Vendored ArchAstroPlatform @ $SHA into $DEST"
