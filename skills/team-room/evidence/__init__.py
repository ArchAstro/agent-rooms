"""Local, stdlib-only construction of safe PR evidence artifacts."""

from .bundle import build_bundle, git_evidence_from_repo
from .model import BundleResult, Chapter, EvidenceEvent, Subject

__all__ = ["BundleResult", "Chapter", "EvidenceEvent", "Subject", "build_bundle", "git_evidence_from_repo"]
