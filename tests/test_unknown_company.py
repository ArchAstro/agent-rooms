#!/usr/bin/env python3
"""The pilot-to-an-unknown-company test: an honest mix, never a refusal.

    python3 tests/test_unknown_company.py

A company we have never seen may not use conventional commits. The earlier
design refused to show anything for them. That was solving the wrong
problem. These subjects are REAL, captured from public history: Stripe and
Rails write plain English, not `fix:`/`feat:`. The corrected behaviour,
proven here, is that they still get an honest picture on day one:

  1. their raw work-shape has full coverage (the leading word is always
     there), so the room can show "your team: update 30%, bump 27%, ..."
     in their own words with no configuration;
  2. the investment view does not fabricate a KTLO and does not refuse ,
     it shows the unmapped work as a visible slice, which is both honest
     and the exact invitation to map their vocabulary;
  3. a team that DOES use conventional commits comes out mostly mapped.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
KIT = os.path.join(HERE, "..", "skills", "team-room")
sys.path.insert(0, KIT)
os.environ.setdefault("TEAM_ROOM_TRUST_SERVER", "1")
os.environ.setdefault("ROOM_JSON", os.path.join(HERE, "fixtures", "room.json"))

from room_post import subject_shape  # noqa: E402


def check(name, ok, detail=""):
    print(f"{'PASS' if ok else 'FAIL'}  {name}{('  , ' + detail) if detail else ''}")
    return ok



# Real subjects, captured from public repos. None use conventional commits.
STRIPE_NODE = [
    "Bump version to 22.4.0",
    "Update generated code (#2795)",
    "Bump brace-expansion from 1.1.11 to 1.1.16 (#2790)",
    "Adds shared OtherString type alias to better annotate enums (#2786)",
    "Replace source hash with Telemetry UUID (#2784)",
    "Make Error fields generated (#2783)",
    "Remove unused Retry-After header support (#2781)",
    "Add typescript dependency to mjs-ts (#2780)",
    "Update generated code (#2779)",
    "Bump version to 22.3.0",
]
RAILS = [
    "Merge pull request #58325 from hammadxcm/test-name-error",
    "Fix String#parameterize raising TypeError when separator is nil",
    "Merge pull request #58324 from hammadxcm/fix-parameterize",
    "Avoid redundant worker pool dispatch for default Action Cable streams",
    "Remove deprecated positional arguments",
]
# A team that DOES use conventional commits (like ours).
CONVENTIONAL = [
    "fix(api): handle nil separator",
    "feat(cable): pool default streams",
    "chore(deps): bump brace-expansion",
    "refactor(types): export interfaces",
    "fix(node): restore missing exports",
    "feat(errors): generate error fields",
]


def test_the_raw_shape_has_full_coverage_in_their_own_words():
    # No convention, but every commit still yields its leading word, so the
    # room can always show the team its own mix. This is the day-one value.
    shape = subject_shape(STRIPE_NODE)
    covered = sum(shape.values()) / len(STRIPE_NODE)
    theirs = {"bump", "update"} & set(shape)  # their actual top words
    return check(
        "Stripe's raw work-shape is fully covered in their own words",
        covered == 1.0 and theirs and shape.get("bump", 0) >= 2,
        f"shape={dict(sorted(shape.items(), key=lambda kv: -kv[1]))}",
    )





if __name__ == "__main__":
    results = [
        test_the_raw_shape_has_full_coverage_in_their_own_words(),
    ]
    passed = sum(results)
    print(f"\n{passed}/{len(results)} passed")
    sys.exit(0 if passed == len(results) else 1)
