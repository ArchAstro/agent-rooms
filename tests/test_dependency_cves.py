#!/usr/bin/env python3
"""Live OSV audit of the pins in this repo; see docs/DEPENDENCY_SECURITY.md.

Direct execution runs deterministic regression cases, then the live E2E.
Use unittest discovery to run only the deterministic cases (no network).
"""

import json
from pathlib import Path
import re
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
OSV = "https://api.osv.dev/v1"


def fetch_json(url, payload=None):
    request = Request(
        url,
        data=None if payload is None else json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "User-Agent": "agent-rooms-cve-check"},
    )
    # Network, HTTP and JSON errors deliberately fail the check, not skip it.
    with urlopen(request, timeout=45) as response:
        return json.load(response)


def inventory(root):
    manifest = json.loads((root / "package.json").read_text())
    for key in ("dependencies", "devDependencies", "optionalDependencies", "peerDependencies"):
        if manifest.get(key):
            raise ValueError(f"package.json now has {key}; extend this audit")

    actions = set()
    for path in sorted((root / ".github/workflows").glob("*.y*ml")):
        for use in re.findall(r"^\s*(?:-\s*)?uses:\s*(\S+)", path.read_text(), re.M):
            match = re.fullmatch(r"([\w.-]+/[\w.-]+)@([0-9a-f]{40})", use)
            if not match:
                raise ValueError(f"{path}: expected an immutable Action SHA, got {use}")
            actions.add(match.groups())
    if not actions:
        raise ValueError("No workflow Action pins found")

    # This deliberately supports the current small XcodeGen packages block,
    # not arbitrary YAML. Reject shape changes instead of silently losing pins.
    text = (root / "macos/project.yml").read_text()
    block = re.search(r"^packages:\n((?:[ \t].*\n|\n)+)", text, re.M)
    if not block:
        raise ValueError("No Swift package pins found")
    packages = re.findall(
        r"^  ([\w-]+):\n    url: (https://github.com/[\w.-]+/[\w.-]+)\n"
        r"    revision: ([0-9a-f]{40})$", block[1], re.M,
    )
    if not packages or len(packages) != len(re.findall(r"^  \S.*:", block[1], re.M)):
        raise ValueError("Swift package inventory changed; extend this audit")
    return sorted(actions), packages


def production_packages(lock):
    if lock.get("lockfileVersion") not in (2, 3) or not lock.get("packages"):
        raise ValueError("Expected an npm v2/v3 lockfile with packages")
    packages = set()
    for path, entry in lock["packages"].items():
        if not path or entry.get("dev"):
            continue
        if "node_modules/" not in path or not entry.get("version") or entry.get("link"):
            raise ValueError(f"Unsupported production lock entry: {path}")
        name = entry.get("name", path.rsplit("node_modules/", 1)[1])
        packages.add((name, entry["version"]))
    if not packages:
        raise ValueError("Action lockfile has no production packages")
    return packages


def osv_findings(queries):
    response = fetch_json(f"{OSV}/querybatch", {"queries": queries})
    results = response["results"]
    if len(results) != len(queries):
        raise ValueError("Incomplete OSV batch response")
    details = {}
    findings = []
    for result in results:
        if result.get("error"):
            raise ValueError(f"OSV query failed: {result['error']}")
        if result.get("next_page_token"):
            raise ValueError("OSV results are paginated; extend this audit before accepting")
        ids = set()
        for item in result.get("vulns", []):
            key = item["id"]
            if key not in details:
                details[key] = fetch_json(f"{OSV}/vulns/{key}")
            advisory = details[key]
            if advisory.get("withdrawn"):
                continue
            cves = {alias for alias in [advisory["id"], *advisory.get("aliases", [])]
                    if alias.startswith("CVE-")}
            ids.update(cves or {advisory["id"]})
        findings.append(ids)
    return findings


def pinned_dependencies_have_no_known_cves(root=ROOT):
    """Fail on actionable Action CVEs or direct Swift advisories; report residuals."""
    actions, swift = inventory(root)
    releases = {}
    dependencies = {}
    for repo, pin in actions:
        if repo not in releases:
            release = fetch_json(f"https://api.github.com/repos/{repo}/releases/latest")
            tag = release["tag_name"]
            ref = fetch_json(f"https://api.github.com/repos/{repo}/git/ref/tags/{tag}")["object"]
            while ref["type"] == "tag":
                ref = fetch_json(ref["url"])["object"]
            if ref["type"] != "commit" or not re.fullmatch(r"[0-9a-f]{40}", ref["sha"]):
                raise ValueError(f"{repo}: release tag does not resolve to a commit")
            releases[repo] = (tag, ref["sha"])
        for revision in (pin, releases[repo][1]):
            key = (repo, revision)
            if key not in dependencies:
                lock = fetch_json(
                    f"https://raw.githubusercontent.com/{repo}/{revision}/package-lock.json"
                )
                dependencies[key] = production_packages(lock)

    npm = sorted(set().union(*dependencies.values()))
    queries = [{"package": {"ecosystem": "npm", "name": name}, "version": version}
               for name, version in npm]
    queries.extend({"commit": revision} for _, _, revision in swift)
    findings = osv_findings(queries)
    by_package = dict(zip(npm, findings[:len(npm)]))
    failures = []
    for repo, pin in actions:
        tag, latest = releases[repo]
        current = set().union(*(by_package[p] for p in dependencies[repo, pin]))
        upstream = set().union(*(by_package[p] for p in dependencies[repo, latest]))
        fixed = current - upstream
        if fixed:
            failures.append(f"{repo}@{pin}: update to {tag} ({latest}) clears {', '.join(sorted(fixed))}")
        print(f"SCAN {repo}@{pin} (latest {tag})", flush=True)
        for package in sorted(dependencies[repo, pin]):
            residual = by_package[package] & upstream
            if residual:
                print(f"  RESIDUAL {package[0]}@{package[1]}: {', '.join(sorted(residual))}", flush=True)
    for (name, url, revision), ids in zip(swift, findings[len(npm):]):
        if ids:
            failures.append(f"{name}@{revision}: {', '.join(sorted(ids))}")
        else:
            print(f"SCAN {name} {url}@{revision}: no OSV matches", flush=True)
    if failures:
        raise AssertionError("\n".join(failures))
    print("PASS pinned_dependencies_have_no_known_cves: no outstanding advisories cleared by "
          "the latest Action releases; no direct Swift commit matches. RESIDUALs are NOT CVE-free.", flush=True)


class ScannerTests(unittest.TestCase):
    def test_inventory_covers_current_pins(self):
        actions, swift = inventory(ROOT)
        self.assertEqual({repo for repo, _ in actions}, {
            "actions/checkout", "actions/setup-python", "actions/setup-node", "actions/upload-artifact",
        })
        self.assertEqual({name for name, _, _ in swift}, {"ArchAstroPlatform", "MarkdownUI", "FluidAudio"})

    def test_inventory_changes_fail_instead_of_skipping(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            workflow = root / ".github/workflows/ci.yml"
            swift = root / "macos/project.yml"
            workflow.parent.mkdir(parents=True)
            swift.parent.mkdir()
            valid_workflow = "steps:\n  - uses: actions/checkout@" + "a" * 40 + "\n"
            valid_swift = (ROOT / "macos/project.yml").read_text()
            for manifest, action_text, swift_text in (
                ({"dependencies": {"new": "1.0.0"}}, valid_workflow, valid_swift),
                ({}, "steps:\n  - uses: actions/checkout@v7\n", valid_swift),
                ({}, valid_workflow, valid_swift.replace("revision:", "branch:")),
            ):
                with self.subTest(manifest=manifest, action=action_text):
                    (root / "package.json").write_text(json.dumps(manifest))
                    workflow.write_text(action_text)
                    swift.write_text(swift_text)
                    with self.assertRaises(ValueError):
                        inventory(root)

    def test_production_lock_includes_nested_scoped_and_optional_not_dev(self):
        lock = {"lockfileVersion": 2, "packages": {
            "": {"name": "action"},
            "node_modules/@actions/core": {"version": "1.0.0"},
            "node_modules/a/node_modules/undici": {"version": "6.0.0", "optional": True},
            "node_modules/alias": {"name": "real-name", "version": "2.0.0"},
            "node_modules/typescript": {"version": "5.0.0", "dev": True},
        }}
        self.assertEqual(production_packages(lock), {
            ("@actions/core", "1.0.0"), ("undici", "6.0.0"), ("real-name", "2.0.0"),
        })
        with self.assertRaises(ValueError):
            production_packages({"lockfileVersion": 1})
        with self.assertRaises(ValueError):
            production_packages({"lockfileVersion": 3, "packages": {"node_modules/x": {}}})

    def test_osv_deduplicates_aliases_and_ignores_withdrawn(self):
        with patch(__name__ + ".fetch_json", side_effect=[
            {"results": [{"vulns": [{"id": "GHSA-a"}, {"id": "GHSA-b"}, {"id": "GHSA-c"}]}]},
            {"id": "GHSA-a", "aliases": ["CVE-2025-7783", "CVE-2025-7783"]},
            {"id": "GHSA-b", "aliases": ["CVE-2020-1"], "withdrawn": "2026-01-01"},
            {"id": "GHSA-c"},
        ]):
            self.assertEqual(osv_findings([{"commit": "x"}]), [{"CVE-2025-7783", "GHSA-c"}])

    def test_incomplete_or_paginated_osv_response_fails(self):
        for response in (
            {"results": []},
            {"results": [{"next_page_token": "more"}]},
            {"results": [{"error": "invalid query"}]},
        ):
            with self.subTest(response=response), patch(__name__ + ".fetch_json", return_value=response):
                with self.assertRaises(ValueError):
                    osv_findings([{"commit": "x"}])

    def run_fixture(self, old_ids, latest_ids, swift_ids=(), error=None):
        old, new = "a" * 40, "b" * 40

        def fetch(url, payload=None):
            if error:
                raise error
            if url.endswith("/releases/latest"):
                return {"tag_name": "v7.0.0"}
            if "/git/ref/tags/" in url:
                return {"object": {"type": "tag", "url": "https://example.test/tag"}}
            if url == "https://example.test/tag":
                return {"object": {"type": "commit", "sha": new}}
            version = "1.0.0" if old in url else "2.0.0"
            return {"lockfileVersion": 3, "packages": {"node_modules/pkg": {"version": version}}}

        with patch(__name__ + ".inventory", return_value=(
            [("actions/example", old)], [("Swift", "https://example.test/swift", "c" * 40)]
        )), patch(__name__ + ".fetch_json", side_effect=fetch), patch(
            __name__ + ".osv_findings", return_value=[set(old_ids), set(latest_ids), set(swift_ids)]
        ), patch("builtins.print") as output:
            pinned_dependencies_have_no_known_cves()
        return "\n".join(str(call) for call in output.call_args_list)

    def test_old_pin_fails_when_release_clears_cve(self):
        with self.assertRaisesRegex(AssertionError, "update to v7.0.0.*CVE-2025-7783"):
            self.run_fixture({"CVE-2025-7783", "CVE-residual"}, {"CVE-residual"})

    def test_no_release_fix_is_reported_not_silenced(self):
        self.assertIn("RESIDUAL pkg@1.0.0: CVE-residual", self.run_fixture({"CVE-residual"}, {"CVE-residual"}))

    def test_no_findings_passes(self):
        self.assertIn("PASS pinned_dependencies_have_no_known_cves", self.run_fixture(set(), set()))

    def test_swift_finding_fails(self):
        with self.assertRaisesRegex(AssertionError, "Swift@.*CVE-swift"):
            self.run_fixture(set(), set(), {"CVE-swift"})

    def test_api_failure_is_not_a_pass(self):
        with self.assertRaisesRegex(OSError, "offline"):
            self.run_fixture(set(), set(), error=OSError("offline"))


if __name__ == "__main__":
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(ScannerTests))
    if not result.wasSuccessful():
        raise SystemExit(1)
    pinned_dependencies_have_no_known_cves()
