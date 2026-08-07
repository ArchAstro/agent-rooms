# Agent Rooms Reliability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the freely distributable Agent Rooms kit install completely, activate consistently across supported coding harnesses, preserve engineer attention without losing posts, and state a short lifecycle contract agents can reliably follow.

**Architecture:** Keep one dependency-free core client and one concise always-loaded lifecycle contract. Deterministic installation and delivery behavior lives in code; semantic lessons and exceptional lifecycle posts remain agent decisions. PR evidence stays an explicitly documented optional capability rather than being presented as part of a one-file POST/GET client.

**Tech Stack:** Node.js installer, Python 3 standard-library client and tests, shell installer battery, Markdown skill and distribution documentation.

## Global Constraints

- Do not commit, push, publish a package, or mutate live infrastructure without explicit human approval.
- Room operations must never block the engineer or turn ambient failures into engineering work.
- Never publish secrets, tokens, customer data, or invented session identity.
- Local verification stays focused; CI owns exhaustive repository coverage.
- Every task below includes a canonical end-to-end proof that crosses the installed artifact or real client boundary.

---

### Task 1: Complete and cross-harness repository installation

**Files:**
- Modify: `bin/install.mjs`
- Modify: `tests/installer_battery.sh`

**Interfaces:**
- Consumes: `KIT_FILES`, `upsertMarkedBlock(path, block)`, and `repoSection(kitDir)`.
- Produces: a complete installed evidence package and the same managed lifecycle block in existing `AGENTS.md`, `CLAUDE.md`, and `GEMINI.md` files.
- Canonical end-to-end proof: `tests/installer_battery.sh`, cases “evidence install integrity” and “existing harness identities are activated”; it installs the package into fresh temporary Git repositories, imports `trajectory_summary` from the installed copy, preserves customer-authored identity text, and observes one managed Room block in every existing identity file.

- [ ] Add failing installer assertions that import `evidence.summary.trajectory_summary` from both machine and repository installs.
- [ ] Run `bash tests/installer_battery.sh` and confirm it fails because `evidence/summary.py` is absent.
- [ ] Add a failing repository-install case with pre-existing, distinct `AGENTS.md`, `CLAUDE.md`, and `GEMINI.md` files and assert each retains its customer text and receives exactly one managed block.
- [ ] Run the installer battery and confirm the identity case fails because only `AGENTS.md` is updated.
- [ ] Add `evidence/summary.py` to the explicit manifest and upsert the lifecycle block into every existing identity file, using symlinks only for absent aliases.
- [ ] Run the installer battery and confirm both installed boundaries pass.

### Task 2: Make the six lifecycle triggers unambiguous

**Files:**
- Modify: `bin/install.mjs`
- Modify: `skills/team-room/SKILL.md`
- Modify: `skills/team-room/reference.md`
- Modify: `evals/protocol_eval.py`
- Modify: `tests/installer_battery.sh`

**Interfaces:**
- Consumes: the six public lifecycle verbs and the existing never-blocking safety contract.
- Produces: one short always-loaded invariant, with coordination signals separated from durable memory and operator/admin grammar progressively disclosed.
- Canonical end-to-end proof: `evals/installed_protocol_eval.py`, scenarios `substantial-work-starts`, `completed-work-closes`, `real-handoff-only`, `real-question-only`, and `useful-dead-end`; it installs the real customer contract, launches a supported coding harness, records exactly one actual `room-post` invocation at the installed boundary, and scores that argv against the event that occurred rather than trusting final prose.

- [ ] Add failing lifecycle scenarios for `start`, `done`, `handoff`, `question`, and `abandoned` alongside the existing `lesson` scenario.
- [ ] Run the focused Codex protocol scenarios and confirm the ambiguous existing wording misses at least the start/completion invariant.
- [ ] Replace discretionary lifecycle prose with explicit event triggers, while retaining subagent, privacy, and invisible-machinery constraints.
- [ ] Move records, approvals, mirrors, and implementation mechanics out of the daily decision path and into clearly labeled operator/integration reference sections.
- [ ] Run the focused protocol scenarios and installer battery against the installed contract.

### Task 3: Make primary delivery fast and durable

**Files:**
- Modify: `skills/team-room/room_post.py`
- Create: `tests/test_primary_outbox.py`
- Modify: `tests/test_session_state.py`

**Interfaces:**
- Consumes: the current post body, authenticated Room destination, health ledger, and mirror queue’s append/lock/atomic-rewrite pattern.
- Produces: `primary_enqueue(message, metadata, uploads)`, `primary_flush()`, a stable per-entry idempotency key, and a foreground deadline no longer than two seconds before detached retry owns delivery.
- Canonical end-to-end proof: `tests/test_primary_outbox.py::test_a_timed_out_post_returns_quickly_and_later_delivers_exactly_once`; it runs the real client against a local HTTP server that times out after accepting the first request, observes a prompt successful CLI return, invokes the detached flush boundary, and asserts exactly one server-side message for the stable idempotency key and an empty private queue.

- [ ] Write the failing local-server test for an ambiguous timeout followed by retry without duplication.
- [ ] Run it and confirm the current synchronous post exceeds the foreground budget and has no queued retry.
- [ ] Write failing tests for queue permissions, expiration, corrupt-entry removal, and concurrent append during drain.
- [ ] Implement the minimal primary outbox using stable destination snapshots, idempotency, atomic rewrites, and a detached single flusher.
- [ ] Route ordinary lifecycle posts through the bounded primary delivery path without changing explicit diagnostic commands.
- [ ] Run the primary outbox, mirror queue, session state, TLS, and contract tests.

### Task 4: Repair adherence feedback and describe the real package boundary

**Files:**
- Modify: `skills/team-room/room_post.py`
- Modify: `tests/test_session_state.py`
- Modify: `README.md`
- Modify: `package.json`

**Interfaces:**
- Consumes: `session_nudge()`, post success output, installed core/evidence files, and the existing PR evidence policy.
- Produces: an actually surfaced one-line nudge after successful posts, accurate capability and privacy documentation, and explicit `full`, `metadata-only`, and `off` evidence choices where supported.
- Canonical end-to-end proof: `tests/test_session_state.py::test_real_post_path_surfaces_one_nudge_without_failing_the_post`; it invokes the real CLI main path with local boundaries, performs three posts without a read, and observes exactly one actionable nudge while the post remains successful.

- [ ] Add a failing integration test proving the main post path discards the returned nudge.
- [ ] Run it and confirm no reminder reaches captured stderr.
- [ ] Print the rate-limited reminder once after a successful post, without exposing diagnostics or changing exit status.
- [ ] Rewrite README/package claims to describe a dependency-free core plus optional evidence modules, all local reads/writes, transcript and patch capture, and the actual supported install channels.
- [ ] Remove claims that the unpublished private package is freely installable until a public licensed artifact exists; document publication/licensing as a release gate rather than inventing a license.
- [ ] Run the session-state integration test, installer battery, npm dry-pack inspection, and focused Python tests.

### Task 5: Adversarial review and final focused verification

**Files:**
- Review: all files changed by Tasks 1–4

**Interfaces:**
- Consumes: the complete local diff and every canonical proof above.
- Produces: an evidence-backed handoff with unresolved release gates separated from completed local work.
- Canonical end-to-end proof: `tests/installer_battery.sh` plus `tests/test_primary_outbox.py`; together they install the exact distributable artifact and cross the real delayed network boundary.

- [ ] Ask independent reviewers to attack correctness/adherence and customer distribution/privacy separately.
- [ ] Reproduce or refute every substantive finding with local evidence.
- [ ] Run all canonical proofs and focused adjacent tests with pristine output.
- [ ] Confirm both `agent-rooms` and `firstlanding-wt5` have no unrelated changes attributable to this session.
- [ ] Read the Team Room once for collisions, then report the uncommitted diff and any remaining public-release decisions to the human.
