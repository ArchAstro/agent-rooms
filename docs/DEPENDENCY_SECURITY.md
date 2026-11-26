# Dependency CVE audit

Audit date: **2026-11-26**. Advisory source: [OSV](https://osv.dev/),
with release tags and npm lockfiles fetched from the upstream GitHub repositories.
This is a dependency advisory check, not a source-code security review or proof
that the application is free of vulnerabilities.

## Findings and remediation

The old GitHub Action pins had known vulnerabilities in their production npm
dependencies. All occurrences in `.github/workflows/*.yml` were updated to the
latest published releases verified at audit time, still pinned to full commit
SHAs:

| Action | Previous SHA | Release | New SHA |
| --- | --- | --- | --- |
| actions/checkout | `11d5960a326750d5838078e36cf38b85af677262` | [v7.0.1](https://github.com/actions/checkout/releases/tag/v7.0.1) | `3d3c42e5aac5ba805825da76410c181273ba90b1` |
| actions/setup-python | `a26af69be951a213d495a4c3e4e4022e16d87065` | [v7.1.0](https://github.com/actions/setup-python/releases/tag/v7.1.0) | `6d4fd22b20465ccc0f7354476588e8df7c9ca0e0` |
| actions/setup-node | `49933ea5288caeca8642d1e84afbd3f7d6820020` | [v7.1.0](https://github.com/actions/setup-node/releases/tag/v7.1.0) | `949feb2413d6458794dcd2491c4babbbce0c15c1` |
| actions/upload-artifact | `ea165f8d65b6e75b540449e92b4886f43607fa02` | [v7.0.2](https://github.com/actions/upload-artifact/releases/tag/v7.0.2) | `cf430e030ddbb5b0abf93d22962f4752f3646cd9` |

Examples removed by these updates:

- **CVE-2025-7783**, critical, predictable multipart boundaries in `form-data`:
  affected the old setup-python, setup-node and upload-artifact pins.
  [Advisory](https://osv.dev/vulnerability/GHSA-fjxv-7rqg-78g4).
- **CVE-2025-25288 / CVE-2025-25289 / CVE-2025-25290**, Octokit regular-expression
  denial of service: affected the old setup-node and upload-artifact pins.
- **CVE-2024-21538**, `cross-spawn` regular-expression denial of service, and
  **CVE-2025-64756**, `glob` CLI command injection: affected the old upload-artifact pin.
- The old checkout pin also had advisories in `@fastify/busboy`, `uuid` and
  `undici` that the new release clears.

These are lockfile matches, **not confirmed exploitable paths in these workflows**.
The new releases use Node 24 for their Action runtime (minimum runner v2.327.1).
The workflows use GitHub-hosted `ubuntu-latest` and `macos-15` runners. Every
explicit input currently used still exists in the new `action.yml` files;
setup-node's requested application Node version remains 20. Actual hosted Action
execution and macOS builds remain CI's responsibility, not locally verified here.

## Outstanding upstream findings

**The new pins are not CVE-free.** At audit time OSV reported **37 distinct CVEs
and one additional GHSA** across their production dependencies. The latest
Action releases checked still contain these findings; updating a local npm
lockfile would not repair the Actions' upstream bundled JavaScript. They are
reported as `RESIDUAL` by the check, not silently suppressed or described as fixed.
Re-run the check and update the Action SHAs when maintainers publish releases
that clear them. We did not fork or rebuild third-party Actions.

The following table groups the union of advisory IDs across each package's
listed versions; the live output maps each exact Action/package/version to its
advisories. IDs can be looked up at `https://osv.dev/list?q=<CVE-ID>`.

| Package | Versions in the updated Actions | Outstanding advisory IDs (union) |
| --- | --- | --- |
| `brace-expansion` | `1.1.12`, `2.0.2`, `5.0.3` | CVE-2026-102276, CVE-2026-102277, CVE-2026-102278, CVE-2026-13149, CVE-2026-14257, CVE-2026-33750, CVE-2026-45149, CVE-2026-69152 |
| `fast-xml-builder` | `1.0.0` | CVE-2026-44665 |
| `fast-xml-parser` | `5.11.2`, `5.4.1`, `5.7.2` | CVE-2026-126066, CVE-2026-33036, CVE-2026-33349, CVE-2026-41650 |
| `glob` | `10.5.0` | CVE-2026-118773 |
| `lodash` | `4.17.23` | CVE-2026-2950, CVE-2026-4800 |
| `minimatch` | `10.2.4`, `10.2.5`, `10.2.6`, `9.0.8` | CVE-2026-118764 |
| `smol-toml` | `1.7.1` | GHSA-r4xh-jqrq-34v2 |
| `undici` | `6.23.0`, `6.27.0`, `6.29.0` | CVE-2026-109383, CVE-2026-109869, CVE-2026-109924, CVE-2026-109932, CVE-2026-11525, CVE-2026-12151, CVE-2026-15157, CVE-2026-1525, CVE-2026-1526, CVE-2026-1527, CVE-2026-1528, CVE-2026-16728, CVE-2026-16729, CVE-2026-18540, CVE-2026-19534, CVE-2026-2229, CVE-2026-6733, CVE-2026-85024, CVE-2026-87018, CVE-2026-9679 |

## Other dependency surfaces and limits

- `package.json` has no npm dependencies; Python client code uses the standard
  library. There are no tracked npm, pip or Cargo lockfiles to audit.
- OSV commit queries returned no matches for the three direct Swift revisions in
  `macos/project.yml`: ArchAstroPlatform `08fb1b5f92ac5f8997d252398a05105810e60bdc`,
  MarkdownUI `5f613358148239d0292c0cef674a3c2314737f9e`, and FluidAudio
  `19600a485baa4998812e4654b70d2bab8f2c9949`. An empty result is not a guarantee
  of OSV coverage for those projects.
- **Unresolved boundary:** there is no `Package.resolved`. MarkdownUI's manifest
  declares `NetworkImage` from 6.0.0, `swift-cmark` from 0.4.0, and the test-only
  `swift-snapshot-testing` from 1.10.0. Their actual build-time resolutions and
  further transitive dependencies are **not audited** by the direct-commit
  queries. Neither ArchAstroPlatform nor FluidAudio declares external SwiftPM
  dependencies at the pinned revisions.
- The Action scan queries non-dev entries (including nested and optional entries)
  in upstream npm v2/v3 lockfiles. It does not prove that an Action's checked-in
  `dist` bundle matches its lockfile, scan Action source-level advisories, or
  audit build-only/dev dependencies, the bundled Node runtime, runner OS,
  Xcode/Homebrew tools, or downloaded speech models.

## Reproduce and CI gate

```sh
# Canonical E2E: includes deterministic cases, then live GitHub/OSV requests.
python3 tests/test_dependency_cves.py

# Deterministic scanner cases only (no network).
python3 -m unittest discover -s tests -p test_dependency_cves.py -v
```

The canonical function is
`tests/test_dependency_cves.py::pinned_dependencies_have_no_known_cves`.
Despite the historical test name, **PASS means no direct Swift commit advisory
and no outstanding Action advisory cleared by the latest published release**,
not zero CVEs. The gate compares advisory IDs across the whole pinned Action
and its latest release; it does not require a version bump for its own sake.
Withdrawn advisories are ignored, CVE aliases are deduplicated, and advisories
without CVE aliases retain their OSV IDs. Residuals are printed even on success.
Inventory, network, API and incomplete/paginated-response errors fail rather
than skip the scan. The check requires public GitHub and OSV access.

Automatic coverage is `.github/workflows/ci.yml` → `kit` → `unit suites`:
its existing `tests/test_*.py` loop executes the live check on pull requests,
pushes to main and manual runs. A live negative run against the old workflow
pins failed with upgrade findings for all four Actions; the updated pins passed.
The deterministic cases also cover old-pin rejection, residual reporting,
Swift advisory failure, production lockfile parsing, withdrawn/aliased
advisories, unsupported inventory changes and API failures.
