"""Native and generic transcript adapters."""
from __future__ import annotations

from pathlib import Path
from typing import Mapping

from .claude import ClaudeAdapter
from .codex import CodexAdapter
from .generic import GenericAdapter


def select_adapter(env: Mapping[str, str], cwd: Path, harness: str | None = None):
    adapters = {"codex": CodexAdapter(), "claude": ClaudeAdapter()}
    if harness:
        if harness not in adapters:
            raise ValueError(f"unsupported harness: {harness}")
        return adapters[harness]
    detected = [adapter for adapter in adapters.values() if adapter.detect(env, cwd) is not None]
    if len(detected) != 1:
        raise ValueError("multiple or missing harnesses; pass --harness explicitly")
    return detected[0]


__all__ = ["ClaudeAdapter", "CodexAdapter", "GenericAdapter", "select_adapter"]
