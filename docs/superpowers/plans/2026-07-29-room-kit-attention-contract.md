# Room Kit Attention Contract Implementation Plan

> **For Codex:** Execute this plan task-by-task with the `superpowers:executing-plans` skill. Use test-driven development for every behavior change.

**Goal:** Make Agent Rooms feel like visible organizational intelligence while keeping capture, retries, diagnostics, and optional integrations out of engineers' coding flow.

**Architecture:** Keep the existing rich Room events and evidence pipeline. Add a single quiet ambient outcome boundary around normal CLI operations, move operational detail into the health ledger and `doctor`, let first-party harness adapters resolve their own session identity, and bound optional fanout with one shared deadline. Keep strict transcript validation and truthful partial recall.

**Tech Stack:** Python 3 standard library CLI and evidence modules, Node installer, shell installer tests, Python protocol evaluation, Firstlanding TypeScript PR controller.

---

## Task 1: Define the ambient attention boundary and fix health deduplication

**Files:**
- Modify: `skills/team-room/room_post.py`
- Modify: `tests/test_session_state.py`
- Add or modify: `tests/test_attention_contract.py`

**Canonical end-to-end proof:** `tests/test_attention_contract.py::test_normal_post_preserves_rich_exhaust_without_emitting_maintenance_work` runs the real CLI as a subprocess against a local HTTP room, injects quality/cadence/drift health conditions, verifies the primary post crosses the network with its metadata, and asserts stdout/stderr contain no maintenance instructions.

1. Add failing tests for one terminal task outcome, silent quality/cadence/drift reporting, and `(component, reason)` health-event count increment without duplicate logical rows.
2. Run the focused tests and confirm they fail for the current multi-message and duplicate-row behavior.
3. Introduce the smallest ambient-output helper needed to separate task outcomes from operator diagnostics.
4. Keep quality, cadence, and drift facts in post metadata or the health ledger, but remove their normal-command stderr output.
5. Correct `health_event` to update the existing logical event and append only when no match exists.
6. Run the focused tests and the existing session-state tests.

## Task 2: Make PR evidence automatic, strict, and quiet

**Files:**
- Modify: `skills/team-room/room_post.py`
- Modify: `skills/team-room/evidence/adapters/base.py`
- Modify: `skills/team-room/evidence/adapters/codex.py`
- Modify: `skills/team-room/evidence/adapters/claude.py`
- Modify: `skills/team-room/evidence/adapters/first_party.py`
- Modify: `skills/team-room/evidence/publisher.py`
- Modify: `tests/test_pr_evidence_adapters.py`
- Modify: `tests/test_pr_evidence_publish.py`

**Canonical end-to-end proof:** `tests/test_pr_evidence_publish.py::test_successful_pr_handoff_without_native_identity_is_quiet_and_self_cleaning` invokes the shipped `room-post pr publish --handoff` process with a private handoff, no usable native identity, and a local room endpoint; it verifies exit success, no engineer-facing remediation, no invented evidence, a recorded health outcome, and removal of the handoff.

1. Replace the existing test that requires `pr evidence withheld` narration with failing quiet/self-cleaning assertions.
2. Add failing process-boundary tests for native first-party auto-detection, exact explicit-session recovery, and native/explicit conflict rejection.
3. Run only the PR adapter and publish tests and confirm the new cases fail.
4. Let first-party adapters resolve native identity from authoritative harness metadata when the handoff omits it.
5. Preserve exact transcript matching, repository binding, symlink rejection, sanitization, and fail-closed conflict handling.
6. Catch configuration/authentication exits at the PR publication boundary, record one health outcome, consume the private handoff, and return success without remediation text.
7. Make explicit diagnostic publication print at most the single status token while automatic handoff publication stays quiet.
8. Run the focused adapter, publish, sanitizer, bundle, conflict, and performance tests.

## Task 3: Bound optional work and keep recall truthful

**Files:**
- Modify: `skills/team-room/room_post.py`
- Modify or add: `tests/test_attention_contract.py`
- Modify: `tests/test_session_state.py`

**Canonical end-to-end proof:** `tests/test_attention_contract.py::test_primary_post_finishes_within_one_budget_when_all_optional_mirrors_fail` runs the real CLI against a successful primary room and multiple deliberately slow local mirror endpoints, verifies the primary event arrives, measures one shared optional deadline rather than serial timeouts, and asserts the coding-session output remains clean.

1. Add failing timing and output tests for several slow/failing optional mirrors.
2. Add failing tests that unavailable recall is distinguishable from a successful empty search, without prescribing login or repair during ambient work.
3. Run the focused tests and confirm current serial delay/output behavior.
4. Give optional fanout one small total deadline and absorb each mirror's setup/network error into health telemetry.
5. Keep direct mentions, conflicts, useful lessons, explicit Room-task failures, and security refusals visible.
6. Preserve an internal unavailable/partial signal for recall so agents cannot falsely claim the Room had no relevant knowledge.
7. Run the focused attention and session-state tests.

## Task 4: Make installation and agent instructions compact and opt-in

**Files:**
- Modify: `skills/team-room/SKILL.md`
- Modify: `skills/team-room/reference.md`
- Modify: `bin/install.mjs`
- Modify: `tests/installer_battery.sh`
- Modify: `evals/protocol_eval.py`

**Canonical end-to-end proof:** `evals/protocol_eval.py` scenario `successful-pr-evidence-exhaust` runs a real coding agent after a successful PR with evidence unavailable and verifies its final response celebrates the PR's useful Room context when present but never mentions login, retry, apology, manual publishing, cleanup, or transport machinery when absent.

1. Add failing installer assertions for repository activation, machine-level capability-only language, subagent silence, repository shim usage, and ambient failure non-narration.
2. Add the failing protocol-eval scenario and retain scenarios proving useful Room lessons and teammate conflicts remain visible.
3. Run the installer battery and the targeted deterministic eval checks.
4. Reduce always-loaded instructions to the approved attention contract; move rationale, examples, internals, updates, and troubleshooting into the reference.
5. Remove contradictory posting cadence and generic “tell the human” requirements.
6. Generate repository instructions that call the guaranteed `scripts/room-post` shim and machine instructions that do not activate arbitrary repositories.
7. Run the installer battery, protocol checks, and instruction-size/drift assertions.

## Task 5: Synchronize Firstlanding and prove the real PR boundary

**Files:**
- Modify: `/Users/vivek/archastro/firstlanding-wt5/scripts/room-post`
- Modify: `/Users/vivek/archastro/firstlanding-wt5/.claude/skills/team-room/**`
- Modify: `/Users/vivek/archastro/firstlanding-wt5/AGENTS.md`
- Modify: `/Users/vivek/archastro/firstlanding-wt5/src/ts/astrodev/packages/core/src/develop/session-store/pr-create-controller.ts`
- Modify or add: `/Users/vivek/archastro/firstlanding-wt5/src/ts/astrodev/packages/core/src/develop/session-store/pr-create-controller*.test.ts`
- Modify: `tests/test_pr_evidence_publish.py`

**Canonical end-to-end proof:** `tests/test_pr_evidence_publish.py::test_firstlanding_pr_creator_crosses_real_cli_boundary_without_attention_leak` executes the production Firstlanding PR controller against the real vendored publisher/CLI with a successful fake PR boundary and unavailable evidence identity, then verifies one successful PR result, no Room remediation in the engineer-facing result, no temporary handoff residue, and byte identity with the canonical kit.

1. Add or strengthen the failing Firstlanding-controller-to-real-CLI process test before changing integration code.
2. Rebase Firstlanding's existing feature branch on `origin/main` while preserving unrelated and untracked user files.
3. Synchronize the canonical kit into Firstlanding using the repository's existing installer/copy path.
4. Change Firstlanding PR guidance and controller invocation only as needed to use the guaranteed repository shim and quiet automatic handoff.
5. Run the canonical Firstlanding boundary test and the focused AstroDev controller test.
6. Verify canonical and vendored kit files are byte-identical.

## Task 6: Review, publish, and enable team testing

**Files:**
- Verify only; update docs/tests only if review exposes a defect.

**Canonical end-to-end proof:** Re-run the five named proofs from Tasks 1–5 together; each crosses a real process or network boundary and asserts both rich organizational exhaust and a clean engineer-facing outcome.

1. Run all focused Room kit tests, installer battery, performance thresholds, and deterministic protocol evaluations.
2. Inspect changed files for accidental secrets, customer data, unrelated work, or relaxed transcript/provenance validation.
3. Ask an unbiased review agent to assess correctness, attention regressions, and hot-path performance; address actionable findings with tests first.
4. Read recent Team Room activity once for collisions.
5. Commit canonical changes, rebase on `origin/main`, push the existing branch, and open a concise canonical PR.
6. Commit Firstlanding changes separately, rebase on `origin/main`, push the existing branch, and open a Firstlanding PR with its required ArchCode-first description and canonical end-to-end proof.
7. Publish PR evidence through the best-effort repository handoff without exposing its internal failure state to the engineer.
8. Report the two ArchCode review links and the exact rebase/install command teammates use to begin testing.
