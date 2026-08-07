#!/usr/bin/env python3
"""The eval harness's contract with unattended runners.

    python3 tests/test_eval_harness.py

An operations job (a scheduled container, a CI step) runs protocol_eval.py
against a VENDORED copy of the kit and publishes a scorecard from its
output. Two things must hold or that scorecard lies: the eval must grade
the SKILL.md it was pointed at, and its result line must separate "the
agent misbehaved" from "the agent never ran". No agent is invoked here —
these are the seams the runner depends on.
"""
import os
import json
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
EVAL = os.path.join(HERE, "..", "evals", "protocol_eval.py")
INSTALLED_EVAL = os.path.join(HERE, "..", "evals", "installed_protocol_eval.py")

PASS = FAIL = 0


def check(label, ok):
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"PASS  {label}")
    else:
        FAIL += 1
        print(f"FAIL  {label}")


def load_eval(skill_path=None):
    """Import protocol_eval as a module with an optional skill override."""
    import importlib.util
    if skill_path:
        os.environ["TEAM_ROOM_SKILL"] = skill_path
    else:
        os.environ.pop("TEAM_ROOM_SKILL", None)
    spec = importlib.util.spec_from_file_location("protocol_eval_probe", EVAL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# --- the eval grades the skill it was pointed at -------------------------
# A consumer vendors the kit; the eval must read THAT copy, or it reports
# on a skill nobody runs.
with tempfile.TemporaryDirectory() as tmp:
    vendored = os.path.join(tmp, "SKILL.md")
    with open(vendored, "w") as fh:
        fh.write("# vendored copy sentinel\n")

    mod = load_eval(vendored)
    check("TEAM_ROOM_SKILL selects the skill under test",
          mod.SKILL.strip() == "# vendored copy sentinel")

mod = load_eval()
check("without the override it falls back to the repo's own skill",
      "room-post" in mod.SKILL)

# The customer-facing proof invokes the real installer and returns the
# always-loaded identities it produced, rather than grading source prose from
# this checkout.
probe = subprocess.run(
    [sys.executable, INSTALLED_EVAL, "--probe"],
    capture_output=True,
    text=True,
    timeout=60,
)
installed = json.loads(probe.stdout) if probe.returncode == 0 else {}
check("installed evaluator grades the generated multi-harness contract",
      probe.returncode == 0
      and "substantial work begins" in installed.get("contract", "").lower()
      and "customer Claude rules" in installed.get("claude", "")
      and "customer Gemini rules" in installed.get("gemini", ""))

# --- the result line separates misbehavior from non-execution ------------
# The runner publishes different incidents for these two, so they can never
# collapse into one number.
scenario_count = len(mod.SCENARIOS)
line = mod.result_line("codex", scenario_count, 0, 0, 0)
check("a clean run reports all passes",
      line == f"RESULT agent=codex pass={scenario_count} fail=0 warn=0 error=0")

regressed = mod.result_line("codex", 6, 2, 0, 0)
check("a behavioral regression reports failures with no errors",
      "fail=2" in regressed and "error=0" in regressed)

never_ran = mod.result_line("codex", 0, scenario_count, 0, scenario_count)
check("an agent that never answered reports errors alongside the failures",
      f"error={scenario_count}" in never_ran)

# --- a missing skill file fails loudly, never silently grades nothing ----
with tempfile.TemporaryDirectory() as tmp:
    missing = os.path.join(tmp, "does-not-exist.md")
    env = dict(os.environ, TEAM_ROOM_SKILL=missing)
    proc = subprocess.run([sys.executable, EVAL, "codex"],
                          capture_output=True, text=True, env=env, timeout=60)
    check("a missing skill path aborts instead of grading an empty skill",
          proc.returncode != 0 and "does-not-exist.md" in proc.stderr)


# --- an agent that never answered must RAISE, not score ------------------
# The defect this guards: subprocess.run does not raise on a non-zero exit,
# so a dead API key or a network outage came back as ordinary output and got
# scored. A no-network run reported "5 passed, 2 failed, 0 errors" while the
# model was unreachable the whole time, which run.sh would have published as
# an agent behavior regression.
import subprocess as _sp

mod = load_eval()
_real_run = _sp.run


class _FakeCompleted:
    def __init__(self, rc, out="", err=""):
        self.returncode, self.stdout, self.stderr = rc, out, err


mod.subprocess.run = lambda *a, **k: _FakeCompleted(1, "", "stream disconnected before completion")
try:
    mod.ask("codex", "anything")
    check("a non-zero agent exit raises instead of being scored", False)
except RuntimeError as exc:
    check("a non-zero agent exit raises instead of being scored",
          "exited 1" in str(exc))
except Exception:
    check("a non-zero agent exit raises instead of being scored", False)

# Exiting 0 while producing no answer is the same incident, not a silent pass.
mod.subprocess.run = lambda *a, **k: _FakeCompleted(0, "some transcript noise", "")
try:
    mod.ask("codex", "anything")
    check("an empty final message raises rather than scoring the transcript", False)
except RuntimeError as exc:
    check("an empty final message raises rather than scoring the transcript",
          "no final message" in str(exc))

# Installed lifecycle evals score the recorder, never an assistant claiming it
# ran a command. A missing call is an execution error; a conflicting final
# answer cannot override the argv actually observed.
os.environ.pop("TEAM_ROOM_EVAL_COMMAND_LOG", None)
mod.subprocess.run = lambda *a, **k: _FakeCompleted(0)
try:
    mod.ask("codex", "start substantial work", require_tool=True)
    check("tool scenarios require an installed command recorder", False)
except RuntimeError as exc:
    check("tool scenarios require an installed command recorder",
          "recorder" in str(exc))

with tempfile.TemporaryDirectory() as tmp:
    command_log = os.path.join(tmp, "calls.jsonl")
    os.environ["TEAM_ROOM_EVAL_COMMAND_LOG"] = command_log

    def fake_agent_without_tool(cmd, **_kwargs):
        answer_path = cmd[cmd.index("-o") + 1]
        with open(answer_path, "w") as handle:
            handle.write('scripts/room-post start "claimed only"')
        return _FakeCompleted(0)

    mod.subprocess.run = fake_agent_without_tool
    try:
        mod.ask("codex", "start substantial work", require_tool=True)
        check("installed eval fails when no command was invoked", False)
    except RuntimeError as exc:
        check("installed eval fails when no command was invoked",
              "without invoking" in str(exc))

    def fake_agent_with_tool(cmd, **_kwargs):
        answer_path = cmd[cmd.index("-o") + 1]
        with open(answer_path, "w") as handle:
            handle.write('scripts/room-post start "wrong final claim"')
        with open(command_log, "w") as handle:
            handle.write('["done", "observed outcome"]\n')
        return _FakeCompleted(0)

    mod.subprocess.run = fake_agent_with_tool
    observed = mod.ask("codex", "finish substantial work", require_tool=True)
    check("installed eval scores recorded argv instead of final prose",
          "TOOL_CALL scripts/room-post done" in observed
          and "wrong final claim" not in observed)

    def fake_agent_with_extra_tool(cmd, **_kwargs):
        answer_path = cmd[cmd.index("-o") + 1]
        with open(answer_path, "w") as handle:
            handle.write("DONE")
        with open(command_log, "w") as handle:
            handle.write('["start", "one"]\n["done", "two"]\n')
        return _FakeCompleted(0)

    mod.subprocess.run = fake_agent_with_extra_tool
    try:
        mod.ask("codex", "start substantial work", require_tool=True)
        check("tool scenarios reject extra lifecycle invocations", False)
    except RuntimeError as exc:
        check("tool scenarios reject extra lifecycle invocations",
              "exactly one" in str(exc))
    os.environ.pop("TEAM_ROOM_EVAL_COMMAND_LOG", None)

# --- the skill's own words can never satisfy a scorer --------------------
# codex echoes the prompt (which embeds the whole SKILL.md) into stdout, and
# the skill documents the very commands the scorers grep for. Scoring the
# transcript therefore passes scenarios on the skill's text alone.
skill_only = mod.SKILL
scored_by_skill = [sc["name"] for sc in mod.SCENARIOS if sc["score"](skill_only)]
check("the skill text alone would satisfy scorers, so answers must be isolated",
      len(scored_by_skill) > 0)

mod.subprocess.run = _real_run

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
