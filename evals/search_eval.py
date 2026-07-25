#!/usr/bin/env python3
"""Room search quality eval.

Iterate on retrieval and catch regressions. Each case is a question a real
session would ask, paired with a phrase that MUST appear in the answer the room
gives back. Cases are drawn from things this team actually re-discovered, so a
pass means the room would have saved someone the rediscovery.

    python3 evals/search_eval.py            # score every case
    python3 evals/search_eval.py -v         # show what came back
    python3 evals/search_eval.py -k 3       # only count the top 3 hits

Scored on:
  hit@k      the gold phrase appears in the top k results (the thing that
             matters — an answer buried at rank 20 is an answer nobody reads)
  rank       where it landed (1 is best)
  precision  share of shown results that carry real knowledge rather than
             status or chatter
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "skills", "team-room"))
import room_post as rp  # noqa: E402

# (query a session would really ask, phrase that must come back, why it matters)
CASES = [
    ("tests pass in CI but fail locally", "direnv",
     "Calvin traced 7 local-only CLI test failures to direnv, not the branch"),
    ("local task api writes all return 500", "event_store",
     "the aggregate_execution_failed pair Calvin and Bruno hit 4 days apart"),
    ("slack agent stopped replying in a channel", "brake",
     "the response brake silences bot-to-bot threads"),
    ("git status and push broke in every worktree at once", "core.bare",
     "a pre-commit run flips core.bare on the shared repo config"),
    ("reading a record my agent's viewer cannot see", "ResidentDeference",
     "UnsafeRepo gets rejected in runtime read paths; use the existing idiom"),
    ("adding an http call to a shared background job broke other tests", "Mox",
     "Rob's lesson on sibling tests failing at runtime"),
]

# The room must also know when it does NOT know. Over-eager retrieval is its
# own failure: confidently handing back an irrelevant lesson is worse than
# silence, because a session will act on it.
NEGATIVE_CASES = [
    "how do I configure the kubernetes ingress for the marketing blog CDN",
]


def evaluate(k: int, verbose: bool) -> int:
    _, _, _, session = rp.read_session()
    hits = 0
    ranks = []
    knowledge_share = []

    for query, gold, why in CASES:
        try:
            items = rp.gather_hits(session, query)
        except Exception as exc:                       # never let the eval die
            print(f"FAIL  {query!r}: search error: {str(exc)[:80]}")
            continue

        ranked = rp.rank_hits(items, query)[:k]
        rank = None
        knowledge = 0
        for i, (it, md, mislabeled) in enumerate(ranked, start=1):
            body = it.get("content") or it.get("text") or ""
            ptype = md.get("post_type")
            if ptype in ("lesson", "abandoned") or mislabeled:
                knowledge += 1
            if rank is None and gold.lower() in body.lower():
                rank = i
        if ranked:
            knowledge_share.append(knowledge / len(ranked))
        if rank:
            hits += 1
            ranks.append(rank)
            print(f"PASS  rank {rank:<2} {query!r}")
        else:
            print(f"MISS  --      {query!r}  (wanted: {why})")
        if verbose:
            for i, (it, md, _m) in enumerate(ranked, start=1):
                head = (it.get("content") or "").strip().split("\n")[0][:88]
                print(f"        {i}. [{md.get('post_type') or 'chatter'}] {head}")

    # Negative control: asking about something the room has never discussed
    # should not surface confident "knowledge". Anything promoted to the top
    # tier here is a false positive a session might act on.
    false_positives = 0
    for query in NEGATIVE_CASES:
        try:
            items = rp.gather_hits(session, query)
        except Exception:
            continue
        top = rp.rank_hits(items, query)[:3]
        bad = [1 for _it, md, mis in top
               if md.get("post_type") in ("lesson", "abandoned") or mis]
        false_positives += len(bad)
        verdict = "PASS" if not bad else f"WARN {len(bad)} confident hit(s)"
        print(f"{verdict}  (negative) {query[:52]!r}")

    total = len(CASES)
    mean_rank = sum(ranks) / len(ranks) if ranks else 0
    prec = sum(knowledge_share) / len(knowledge_share) if knowledge_share else 0
    print(f"\nhit@{k}: {hits}/{total} ({100 * hits / total:.0f}%)"
          f"   mean rank: {mean_rank:.1f}"
          f"   knowledge in results: {100 * prec:.0f}%"
          f"   false positives: {false_positives}")
    return 0 if hits == total else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("-k", type=int, default=5, help="how many results count")
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args()
    sys.exit(evaluate(a.k, a.verbose))
