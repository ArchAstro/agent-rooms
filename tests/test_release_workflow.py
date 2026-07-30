#!/usr/bin/env python3
"""Regression checks for the public macOS release asset contract."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = (ROOT / ".github" / "workflows" / "release-dmg.yml").read_text()


def check(label: str, condition: bool) -> None:
    if not condition:
        raise AssertionError(label)
    print(f"PASS  {label}")


check(
    "the reviewed release tag is available to the packaging step",
    "TAG: ${{ needs.resolve-release.outputs.tag }}" in WORKFLOW,
)
check(
    "the public DMG filename includes the marketing version",
    'DMG="$GITHUB_WORKSPACE/dist/Rooms-${VERSION}.dmg"' in WORKFLOW,
)
check(
    "the version is derived from the already-validated release tag",
    'VERSION="${TAG#v}"' in WORKFLOW,
)
check(
    "release CI no longer publishes the unversioned filename",
    'dist/Rooms.dmg' not in WORKFLOW,
)
check(
    "the Actions artifact is versioned too",
    "name: Rooms-${{ needs.resolve-release.outputs.tag }}-dmg" in WORKFLOW,
)
