# Room Kit Organizational Signal and Engineer Attention Design

## Purpose

Agent Rooms is an organizational nervous system embedded in coding work. The
kit should continuously emit the high-value exhaust an organization needs for
shared knowledge, insight, review, and action while making that intelligence
available inside coding sessions at the moments it materially helps.

The kit is not a workflow engineers operate. Its own setup, telemetry,
bookkeeping, optional fanout, evidence capture, and health failures must not
become work for an engineer who is trying to ship code.

This yields two simultaneous requirements:

1. Preserve or improve the richness, fidelity, and reliability of
   organizational exhaust.
2. Spend engineer attention only when Room information changes or materially
   helps the coding task.

Silencing useful capture is not an acceptable way to make the kit quiet.

## Governing Attention Contract

Normal coding-session behavior has two audiences:

- **The organization:** receives durable coding exhaust, provenance, lessons,
  decisions, status, PR evidence, and health telemetry.
- **The engineer:** receives only information that is relevant enough to
  justify interrupting the coding flow.

The kit may interrupt an engineer for:

- a teammate finding, ownership collision, or approved record that conflicts
  with the work they are about to do;
- a direct request or mention addressed to them;
- a security refusal that protects credentials or prevents posting to an
  untrusted destination;
- a one-time browser interaction while the engineer is explicitly onboarding
  or diagnosing Agent Rooms;
- failure of a Room operation the engineer explicitly requested as the task,
  rather than ambient coordination performed alongside another task.

The kit must not interrupt an engineer for:

- unavailable PR evidence after the PR itself succeeded;
- optional mirror or enrichment failures;
- post-shape lint, cadence reminders, freshness checks, latency measurements,
  version drift, or absorbed internal errors;
- unavailable ambient reads or writes beyond the smallest truthful status the
  coding agent needs to avoid false claims;
- login, retry, repair, update, or diagnostic work during an unrelated coding
  task.

Coding agents must not repeat, apologize for, troubleshoot, or assign manual
cleanup for these non-actionable failures. The durable health ledger and
explicit `room-post doctor` command are the operator surface for them.

## Runtime Design

### One terminal outcome per command

Every ambient command returns success to the coding workflow and produces at
most one truthful task-level outcome. It must not concatenate setup guidance,
generic post failure text, and subsystem-specific failure text.

PR evidence publication always resolves to exactly one of:

- `published`
- `updated`
- `unchanged`
- `queued`
- `withheld`

Automatic publication uses a quiet path: a withheld result is health-logged
but produces no engineer-facing remediation. Explicit diagnostic invocation
may display the status, but still must not prescribe work that cannot succeed.

### Harness-owned identity

Native harness metadata belongs to the harness and publisher, not the coding
agent. Codex and Claude publication auto-detect their current native session
identity and validate one exact transcript against authoritative internal
metadata. The handoff does not require a model-authored session identifier.

An explicit session identifier is accepted only if it can actually resolve an
exact validated transcript when the native environment variable is absent.
Conflicting native and explicit identities are rejected rather than guessed.
The existing fail-closed transcript, privacy, and provenance guarantees remain
unchanged.

### Hot-path silence, diagnostic depth

Normal posts retain rich metadata and health recording but do not print:

- post-quality warnings;
- read-cadence nudges;
- optional mirror setup or failure messages;
- legacy-install, freshness, or drift remediation.

Optional mirrors share one small total latency budget and cannot serially add
multi-second delays to a successful primary-room post.

`room-post doctor` remains detailed and actionable. It reports configuration,
authentication, read/search health, mirrors, integrity, freshness, absorbed
errors, and cadence/quality telemetry. This preserves operational
observability without charging every coding session for it.

Health events deduplicate by `(component, reason)` and increment their count;
one repeated failure must not create multiple logical warning rows.

### Truthful recall degradation

Room recall must never turn a failed query into a false “no knowledge found”
result. Ambient recall may tell the coding agent that results are unavailable
or partial, because that changes how confidently it can rely on Room context.
The agent continues the coding task silently unless the missing Room result is
itself the user’s requested task.

Direct teammate conflicts, mentions, and useful retrieved lessons remain
visible. Quietness must not hide organizational intelligence that helps the
engineer.

## Instruction and Installation Design

Always-loaded instructions become a compact behavioral contract:

- Agent Rooms activates only in explicitly enabled repositories.
- Top-level sessions doing nontrivial coding work read once at task start,
  search the relevant subsystem/behavior, and post only durable findings or
  useful lifecycle outcomes.
- Subagents may read but never post.
- Before committing or opening a PR, the owner reads recent Room activity once
  for collisions.
- PR-producing harnesses publish evidence automatically through the repository
  shim.
- Ambient Room failure is never narrated, retried, diagnosed, or handed to the
  engineer.
- Secrets and customer data are never posted.

The machine installer advertises capability but does not imply that every
repository participates. Repository installation is the activation boundary.
Onboarding and update commands live in installer output and the reference,
not in every coding session’s behavioral prompt.

The operational skill states the executable rules once. Rationale, examples,
adapter internals, and troubleshooting move to the reference so they remain
available without consuming every agent’s working attention.

Repository-specific PR guidance uses `scripts/room-post`, which the repository
install guarantees, rather than assuming a machine-global `room-post`.

## Verification

### Canonical end-to-end proof

`evals/protocol_eval.py` scenario `successful-pr-evidence-exhaust` runs a real
coding agent with this situation:

- a PR was created successfully;
- native session metadata is unavailable;
- best-effort evidence publication completed without publishing.

The agent must report the successful PR without mentioning Room failure,
login, retry, apology, manual publication, cleanup, or user action.

### Process-boundary proofs

`tests/test_pr_evidence_publish.py` will cover:

- a private handoff with an omitted session ID using native auto-detection;
- missing native and explicit session metadata withholding quietly and
  consuming the handoff;
- explicit exact-session recovery without a native environment variable;
- conflict between native and explicit session identities failing closed;
- the Firstlanding PR creator crossing the real publisher/CLI boundary while
  preserving one successful PR outcome and leaving no temporary residue.

Additional focused tests will prove:

- normal post-quality, cadence, mirror, and drift failures stay off stderr;
- optional mirror fanout respects one bounded total deadline;
- health events actually deduplicate and increment;
- partial/unavailable recall remains distinguishable from an empty result;
- generated machine and repository instructions preserve opt-in and attention
  semantics;
- the canonical kit and Firstlanding vendored kit remain byte-identical after
  synchronization.

## Scope

This change modifies the local kit, its installer/instructions, behavioral
evals, and Firstlanding’s vendored integration. It does not change room server
APIs, authorization policy, artifact storage, evidence payload content,
sanitization, transcript validation strictness, or resident review routines.

