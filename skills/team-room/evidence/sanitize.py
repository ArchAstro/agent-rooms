"""Redact untrusted evidence before it reaches any durable artifact."""
from __future__ import annotations

from collections import Counter
from dataclasses import replace
import re
from typing import Any, Callable, Mapping

from .model import EvidenceEvent, Omission, Redaction, thaw


class SanitizationError(RuntimeError):
    """Sanitization did not complete; callers must withhold inspected data."""


# Fixed-width common forms prevent a split token from greedily consuming an
# adjacent ordinary field. Organization policy may add broader patterns later.
_TOKEN_RE = re.compile(r"(?:sk_(?:live|test)_[A-Za-z0-9_-]{16,}|sk-proj-[A-Za-z0-9_-]{16,}|github_pat_[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9_-]{36,}|AKIA[0-9A-Z]{16})")
_PRIVATE_KEY_RE = re.compile(
    r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z0-9 ]*PRIVATE KEY-----"
)
_JWT_RE = re.compile(r"\beyJ[A-Za-z0-9_-]*\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+")
_DATABASE_URL_RE = re.compile(
    r"\b(?:postgres(?:ql)?|mysql|mariadb|mongodb(?:\+[a-z0-9]+)?|redis(?:s)?):\/\/[^\s'\"]+",
    re.IGNORECASE,
)
_SLACK_TOKEN_RE = re.compile(r"\bxox(?:a|b|p|r|s)-[A-Za-z0-9-]{10,}")
_AUTHORIZATION_RE = re.compile(
    r"\bAuthorization\s*:\s*(?:Basic\s+\S+|Bearer\s+(?!sk_(?:live|test)_|sk-proj-|github_pat_|gh[pousr]_)[^\s]+)",
    re.IGNORECASE,
)
_BEARER_TOKEN_RE = re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{16,}", re.IGNORECASE)
_BASIC_TOKEN_RE = re.compile(r"\bBasic\s+[A-Za-z0-9+/]{8,}={0,2}", re.IGNORECASE)


def _scan_string(value: str) -> tuple[str, list[Redaction]]:
    redactions: list[Redaction] = []

    def redact(pattern: re.Pattern[str], marker: str, category: str, text: str) -> str:
        safe, count = pattern.subn(marker, text)
        if count:
            redactions.append(Redaction(category, count))
        return safe

    # Refuse complete key blocks rather than attempting to preserve any
    # potentially sensitive lines within them. The remaining forms are kept
    # as typed markers so a reviewer can see why evidence was omitted.
    value = redact(_PRIVATE_KEY_RE, "[REDACTED:private_key]", "private_key", value)
    value = redact(_AUTHORIZATION_RE, "Authorization: [REDACTED:authorization]", "authorization", value)
    value = redact(_JWT_RE, "[REDACTED:bearer_token]", "bearer_token", value)
    value = redact(_BEARER_TOKEN_RE, "Bearer [REDACTED:bearer_token]", "bearer_token", value)
    value = redact(_BASIC_TOKEN_RE, "Basic [REDACTED:authorization]", "authorization", value)
    value = redact(_DATABASE_URL_RE, "[REDACTED:database_url]", "database_url", value)
    value = redact(_SLACK_TOKEN_RE, "[REDACTED:slack_token]", "slack_token", value)
    value = redact(_TOKEN_RE, "[REDACTED:api_token]", "api_token", value)
    return value, redactions


def _credential_key_marker(key: str) -> tuple[str, str] | None:
    """Identify named credential containers without guessing from prose values."""
    if key.startswith("[REDACTED:"):
        return None
    separated = re.sub(r"([a-z])([A-Z])", r"\1 \2", key)
    parts = {part for part in re.split(r"[^a-z0-9]+", separated.lower()) if part}
    if "authorization" in parts:
        return "[REDACTED:authorization]", "authorization"
    if parts & {"password", "passwd", "secret", "credential", "credentials", "token", "apikey", "api", "private"}:
        return "[REDACTED:credential]", "credential"
    return None


def _merge(redactions: list[Redaction]) -> tuple[Redaction, ...]:
    counts: Counter[str] = Counter()
    for item in redactions:
        counts[item.category] += item.count
    return tuple(Redaction(category, count) for category, count in sorted(counts.items()))


def _sanitize(value: Any, scanner: Callable[[str], tuple[str, list[Redaction]]]) -> tuple[Any, list[Redaction]]:
    if isinstance(value, str):
        return scanner(value)
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        redactions: list[Redaction] = []
        for key, item in value.items():
            marker = _credential_key_marker(str(key))
            if marker is not None:
                # Still scan the discarded value so redaction accounting stays
                # truthful and scanner failures fail closed.
                _, found = _sanitize(item, scanner)
                result[str(key)] = marker[0]
                redactions.append(Redaction(marker[1]))
                redactions.extend(found)
            else:
                safe, found = _sanitize(item, scanner)
                result[str(key)] = safe
                redactions.extend(found)
        return result, redactions
    if isinstance(value, list) or isinstance(value, tuple):
        values, all_redactions = [], []
        for item in value:
            safe, found = _sanitize(item, scanner)
            values.append(safe)
            all_redactions.extend(found)
        return values, all_redactions
    if value is None or isinstance(value, (int, float, bool)):
        return value, []
    raise SanitizationError(f"unsupported value for sanitization: {type(value).__name__}")


def sanitize(value: Any, scanner: Callable[[str], tuple[str, list[Redaction]]] = _scan_string) -> tuple[Any, tuple[Redaction, ...]]:
    try:
        safe, redactions = _sanitize(value, scanner)
    except Exception as exc:
        if isinstance(exc, SanitizationError):
            raise
        raise SanitizationError(str(exc)) from exc
    # Detect fixed token forms deliberately split across mapping structure,
    # including a key/value pair and consecutive keys. This is intentionally
    # limited to scanner-recognized credential forms; arbitrary prose is never
    # concatenated or redacted merely because it crosses a field boundary.
    structural: dict[int, tuple[set[str], set[str]]] = {}
    def structural_boundaries(item: Any) -> None:
        if isinstance(item, Mapping):
            entries = [(str(key), child) for key, child in item.items()]
            secret_keys, secret_values = set(), set()
            for key, child in entries:
                if isinstance(child, str):
                    _, key_found = scanner(key)
                    _, value_found = scanner(child)
                    _, joined_found = scanner(key + child)
                    if not key_found and not value_found and joined_found:
                        secret_keys.add(key); secret_values.add(key); redactions.extend(joined_found)
            for (left, _), (right, _) in zip(entries, entries[1:]):
                _, left_found = scanner(left)
                _, right_found = scanner(right)
                _, joined_found = scanner(left + right)
                if not left_found and not right_found and joined_found:
                    secret_keys.update((left, right)); redactions.extend(joined_found)
            structural[id(item)] = (secret_keys, secret_values)
            for _, child in entries: structural_boundaries(child)
        elif isinstance(item, list):
            for child in item: structural_boundaries(child)
    try:
        structural_boundaries(safe)
    except Exception as exc:
        raise SanitizationError(str(exc)) from exc

    # Preserve mapping cardinality while sanitizing keys. A bare marker would
    # collide for two secret keys and silently discard data.
    def keys(item: Any) -> Any:
        if isinstance(item, Mapping):
            out, used = {}, set()
            structural_keys, structural_values = structural.get(id(item), (set(), set()))
            # Reserve every literal key before allocating secret markers. This
            # makes collision handling independent of insertion order.
            reserved = set()
            for original_key in item:
                rendered, _ = scanner(str(original_key)) if str(original_key) not in structural_keys else ("[REDACTED:api_token]", [])
                if rendered == str(original_key):
                    reserved.add(rendered)
            for key, child in item.items():
                rendered, found = scanner(str(key)) if str(key) not in structural_keys else ("[REDACTED:api_token]", [])
                redactions.extend(found)
                if rendered != str(key):
                    base, n = "[REDACTED:api_token]", 1
                    rendered = base
                    while rendered in used or rendered in reserved:
                        n += 1; rendered = f"{base}#{n}"
                used.add(rendered)
                out[rendered] = "[REDACTED:api_token]" if str(key) in structural_values else keys(child)
            return out
        if isinstance(item, list): return [keys(child) for child in item]
        return item
    try:
        safe = keys(safe)
    except Exception as exc:
        raise SanitizationError(str(exc)) from exc
    # Flatten only value leaves with exact offsets. This catches a token split
    # over any nested/list boundary without redacting unrelated IDs or prompts.
    refs: list[tuple[Any, Any, str]] = []
    def gather(parent: Any, key: Any, item: Any) -> None:
        if isinstance(item, Mapping):
            for child_key, child in item.items(): gather(item, child_key, child)
        elif isinstance(item, list):
            for index, child in enumerate(item): gather(item, index, child)
        elif isinstance(item, str): refs.append((parent, key, item))
    gather(None, None, safe)
    joined, ranges, cursor = "", [], 0
    for parent, key, text in refs:
        ranges.append((cursor, cursor + len(text), parent, key, text)); joined += text; cursor += len(text)
    candidates: list[tuple[int, int]] = []
    prefixes = (("sk_live_", 16), ("sk_test_", 16), ("sk-proj-", 16), ("github_pat_", 20), ("ghp_", 36), ("gho_", 36), ("ghu_", 36), ("ghs_", 36), ("ghr_", 36), ("AKIA", 16))
    for prefix, minimum in prefixes:
        offset = joined.find(prefix)
        while offset >= 0:
            required = offset + len(prefix) + minimum
            end = next((entry[1] for entry in ranges if entry[1] >= required), None)
            if end is not None:
                candidates.append((offset, end))
            offset = joined.find(prefix, offset + 1)
    for match_start, match_end in reversed(candidates):
        touched = [entry for entry in ranges if entry[0] < match_end and entry[1] > match_start]
        for start, end, parent, key, text in touched:
            left = max(0, match_start - start); right = min(len(text), match_end - start)
            replacement = text[:left] + "[REDACTED:api_token]" + text[right:]
            if parent is not None: parent[key] = replacement
        redactions.append(Redaction("api_token"))
    return safe, _merge(redactions)


def _bounded(value: str, limit: int) -> tuple[str, bool]:
    if len(value) <= limit:
        return value, False
    if limit < 2:
        return value[:limit], True
    return value[:limit - 1] + "…", True


def sanitize_event(event: EvidenceEvent, tool_excerpt_limit: int = 8192) -> tuple[EvidenceEvent, tuple[Omission, ...]]:
    summary, summary_cut = _bounded(event.summary, tool_excerpt_limit) if event.type == "tool_result" else (event.summary, False)
    data = thaw(event.data)
    cut = summary_cut
    def bound_nested(value: Any) -> Any:
        nonlocal cut
        if isinstance(value, str):
            bounded, was_cut = _bounded(value, tool_excerpt_limit)
            cut = cut or was_cut
            return bounded
        if isinstance(value, Mapping): return {str(key): bound_nested(child) for key, child in value.items()}
        if isinstance(value, list) or isinstance(value, tuple): return [bound_nested(child) for child in value]
        return value
    if event.type == "tool_result":
        data = bound_nested(data)
    omissions = (Omission("tool_excerpt", f"bounded to {tool_excerpt_limit} UTF-8 characters"),) if cut else ()
    # The bundle sanitizes this complete normalized chapter immediately before
    # serialization, so it can aggregate typed redaction accounting once.
    return replace(event, summary=summary, data=data), omissions
