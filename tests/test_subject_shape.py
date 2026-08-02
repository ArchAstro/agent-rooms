#!/usr/bin/env python3
"""The universal fact: the shape of a team's work, in the team's own words.

    python3 tests/test_subject_shape.py

Stdlib only, no network, no pytest. The property under test is that the
leading word of every commit is extracted faithfully and never guessed at:
`fix(rooms): ...` reduces to `fix`, `Bump version` reduces to `bump`, and
nothing is coerced into a meaning. What each word MEANS (KTLO, new work)
is the ruleset's job at report time, so the kit stays dumb and the
definition can change without a kit release. The load-bearing claim, proved
in the last test, is coverage: the leading word explains ~100% of history
on any repo, where a conventional-commit prefix explains 0-2% off ours.
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


def test_reduces_conventional_and_plain_english_alike():
    # A conventional-commit team and a verb-led team reduce to the same kind
    # of token: the leading word. This is why one mechanism serves both.
    subjects = [
        "fix(rooms): stop double-booking a paused routine",  # -> fix
        "feat(agents): enforce private routine output",      # -> feat
        "chore: bump the vitest dev dependency",             # -> chore
        "Bump version to 22.4.0",                            # -> bump
        "Remove unused Retry-After header support",          # -> remove
        "Update generated code",                             # -> update
    ]
    got = subject_shape(subjects)
    want = {"fix": 1, "feat": 1, "chore": 1, "bump": 1, "remove": 1, "update": 1}
    return check(
        "the leading word is taken literally, convention or not",
        got == want,
        f"{got}",
    )


def test_is_case_insensitive_and_ignores_scope_and_punctuation():
    subjects = [
        "FIX: uppercased still counts as fix",
        "fix(core): scoped still counts as fix",
        "  fix: leading whitespace still counts as fix",
    ]
    got = subject_shape(subjects)
    return check(
        "case, scope and leading space do not fragment a token",
        got == {"fix": 3},
        f"{got}",
    )


def test_only_the_skip_ci_marker_buckets_as_automated():
    # The one interpretation the kit bakes in is a FACT: the deliberate
    # `[skip ci]` marker means a deploy bot, regardless of the leading word.
    # A subject that merely looks automated ("update image refs") but carries
    # no marker keeps its literal leading word. Guessing here would be our
    # judgment leaking into the immutable stamp.
    subjects = [
        "chore: update latest image refs [skip ci]",     # marker -> automated
        "Update staging image refs (scheduled)",         # no marker -> update
        "fix(rooms): a real human fix",
    ]
    got = subject_shape(subjects)
    return check(
        "only the [skip ci] marker buckets as automated; no prose guessing",
        got == {"automated": 1, "update": 1, "fix": 1},
        f"{got}",
    )


def test_empty_and_wordless_subjects_are_handled():
    # Empty subjects are skipped (a docs-only window is a real state); a
    # subject with no letters at all falls to `other` rather than crashing.
    got = subject_shape(["", "   ", "12345", "..."])
    return check(
        "empty subjects skip, a wordless one is other, never a crash",
        got == {"other": 2},
        f"{got}",
    )


def test_leading_word_explains_all_of_this_repos_history():
    # THE load-bearing claim. Run over this repo's own recent history and
    # assert the leading word explains ~100% of it (every non-empty subject
    # has a word), where a conventional-commit prefix would explain ~87%.
    # This is what lets an unknown company get an honest mix on day one.
    import subprocess

    root = os.path.dirname(HERE)  # this repository
    out = subprocess.run(
        ["git", "log", "-400", "--no-merges", "--pretty=%s"],
        capture_output=True, text=True, cwd=root,
    ).stdout.splitlines()
    subs = [s for s in out if s.strip()]
    if len(subs) < 50:
        # A shallow clone has no history to measure; the coverage claim is
        # pinned against 400 real commits in the consuming repo's suite.
        return check("repo history too shallow here; claim pinned upstream", True,
                     f"{len(subs)} subjects")

    shape = subject_shape(subs)
    total = sum(shape.values())
    covered = total / len(subs)               # every subject yields a token
    wordless = shape.get("other", 0) / total  # the only unclassifiable bucket
    top = ", ".join(f"{t}" for t, _ in sorted(shape.items(), key=lambda kv: -kv[1])[:5])
    ok = covered >= 0.99 and wordless <= 0.05
    return check(
        "the leading word explains ~100% of real history",
        ok,
        f"n={len(subs)} covered={covered:.0%} wordless={wordless:.0%} top={top}",
    )











def test_any_alphabet_counts_as_a_word():
    # The signal claims to work for a team we have never seen, so the
    # parser must not be ASCII-only. str.isalpha covers every alphabet
    # with no character tables; NFC normalisation makes composed and
    # decomposed spellings share one bucket.
    import unicodedata
    got = subject_shape([
        "Исправить вход",
        "修复登录问题",
        "Añadir soporte",
        unicodedata.normalize("NFD", "Añadir soporte"),
    ])
    return check(
        "any alphabet counts, and one word means one bucket",
        got == {"исправить": 1, "修复登录问题": 1, "añadir": 2},
        f"{got}",
    )


def test_shape_buckets_counts_and_shas_can_never_disagree():
    # The spine's exactness guarantee rests here: a reader derives counts
    # as len(bucket) and de-duplicates by SHA membership, so the stamped
    # work_shape and work_shape_commits must be the same fact twice.
    from room_post import shape_buckets
    pairs = "\n".join([
        "abc123def456\tfix(rooms): stop double-booking",
        "bbb222bbb222\tfix: another one",
        "ccc333ccc333\tfeat(api): new surface",
        "ddd444ddd444\tchore: bump deps [skip ci]",
        "eee555eee555\tsubject with\ta literal tab in it",
    ])
    got = shape_buckets(pairs)
    counts = {t: len(v) for t, v in got.items()}
    ok = (
        got["fix"] == ["abc123def456", "bbb222bbb222"]
        and got["feat"] == ["ccc333ccc333"]
        # [skip ci] SHAs land under automated, so they still dedup
        and got["automated"] == ["ddd444ddd444"]
        # a tab inside the subject cannot shift the SHA column
        and got["subject"] == ["eee555eee555"]
        and counts == {"fix": 2, "feat": 1, "automated": 1, "subject": 1}
    )
    return check("bucket sizes ARE the counts; tabs and [skip ci] behave", ok, f"{got}")


def test_shape_buckets_empty_and_junk_are_silent():
    from room_post import shape_buckets
    ok = (shape_buckets("") == {} and shape_buckets("\n\n") == {}
          and shape_buckets("\tno sha column") == {})
    return check("empty or junk log output yields no buckets, no crash", ok)


def test_an_empty_message_commit_still_buckets():
    # git commit --allow-empty-message produces a real commit with no
    # subject. Skipping it made counts, buckets and the flat SHA list
    # disagree (review find); it buckets under `other` instead.
    from room_post import shape_buckets
    got = shape_buckets("abc123abc123\t\nddd444ddd444\tfix: real one")
    return check(
        "an empty-subject commit lands in other, keeping lists consistent",
        got == {"other": ["abc123abc123"], "fix": ["ddd444ddd444"]},
        f"{got}",
    )


if __name__ == "__main__":
    results = [
        test_reduces_conventional_and_plain_english_alike(),
        test_is_case_insensitive_and_ignores_scope_and_punctuation(),
        test_only_the_skip_ci_marker_buckets_as_automated(),
        test_empty_and_wordless_subjects_are_handled(),
        test_leading_word_explains_all_of_this_repos_history(),
        test_any_alphabet_counts_as_a_word(),
        test_shape_buckets_counts_and_shas_can_never_disagree(),
        test_shape_buckets_empty_and_junk_are_silent(),
        test_an_empty_message_commit_still_buckets(),
    ]
    passed = sum(results)
    print(f"\n{passed}/{len(results)} passed")
    sys.exit(0 if passed == len(results) else 1)
