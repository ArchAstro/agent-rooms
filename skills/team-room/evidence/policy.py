"""Built-in complete capture with explicit local narrowing modes."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


MODES = frozenset({"review_capsule", "metadata_only", "local_review"})


@dataclass(frozen=True)
class Policy:
    mode: str = "review_capsule"
    allow_prompts: bool = True
    allow_trajectory: bool = True
    allow_patch: bool = True
    max_bytes: int = 3 * 1024 * 1024

    def __post_init__(self):
        if self.mode not in MODES or not 1 <= self.max_bytes <= 3 * 1024 * 1024:
            raise ValueError("invalid evidence publication policy")


def policy_for_mode(mode: str | None) -> Policy:
    """Return the complete default or an explicitly narrower local capture."""
    selected = (mode or "review_capsule").replace("-", "_")
    if selected not in MODES:
        raise ValueError("unknown evidence capture mode")
    wanted = {
        "review_capsule": (True, True, True),
        "metadata_only": (True, True, False),
        "local_review": (False, False, False),
    }[selected]
    return Policy(selected, *wanted)


def restrict_payload(payload: Mapping[str, Any], policy: Policy) -> dict[str, Any]:
    """Make mode omissions explicit in already-safe local evidence JSON."""
    import copy
    out = copy.deepcopy(dict(payload))
    omissions = list(out.get("omissions") or [])
    if not policy.allow_prompts:
        for chapter in out.get("chapters", []):
            chapter["prompts"] = []
        omissions.append({"category": "prompts", "reason": "local capture mode"})
    if not policy.allow_trajectory:
        for chapter in out.get("chapters", []):
            chapter["events"] = []
        omissions.append({"category": "trajectory", "reason": "local capture mode"})
    if not policy.allow_patch:
        patch = out.setdefault("patch", {})
        patch["text"] = ""
        omissions.append({"category": "patch", "reason": f"{policy.mode} local capture mode"})
    out["omissions"] = omissions
    out.setdefault("current", {})["capture_mode"] = policy.mode
    if omissions:
        out["current"]["complete"] = False
    if not (policy.allow_prompts and policy.allow_trajectory and policy.allow_patch):
        # The initial human rendering was generated from the full local bundle.
        # Never leave omitted material embedded in that convenience view.
        subject = out.get("subject", {})
        out["rendered_markdown"] = (
            f"## Evidence for {subject.get('key', 'unknown')}\n\n"
            f"Head: `{subject.get('head_sha', 'unknown')}`\n\n"
            f"Capture mode: `{policy.mode}`\n"
        )
    return out
