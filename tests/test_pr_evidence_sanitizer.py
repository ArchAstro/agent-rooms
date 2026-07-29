#!/usr/bin/env python3
"""Focused safety contracts for evidence sanitization.

Run with: python3 tests/test_pr_evidence_sanitizer.py
"""
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills" / "team-room"))

from evidence.sanitize import SanitizationError, sanitize, sanitize_event  # noqa: E402
from evidence.model import EvidenceEvent  # noqa: E402


def test_sensitive_token_split_across_ordinary_fields_is_replaced_with_typed_marker():
    # Detecting only each leaf would leak a token deliberately split by a tool exporter.
    original = {
        "tool": "curl", "header_prefix": "Authorization: Bearer sk_live_",
        "header_suffix": "1234567890abcdef", "note": "ordinary visible output",
    }
    safe, redactions = sanitize(original)
    assert safe == {
        "tool": "curl", "header_prefix": "Authorization: Bearer [REDACTED:api_token]",
        "header_suffix": "[REDACTED:api_token]", "note": "ordinary visible output",
    }
    assert [(item.category, item.count) for item in redactions] == [("api_token", 1)]
    print("PASS  test_sensitive_token_split_across_ordinary_fields_is_replaced_with_typed_marker")


def test_sanitizer_failure_is_a_typed_failure_not_unsanitized_output():
    def broken(_: str) -> tuple[str, list]:
        raise RuntimeError("detector unavailable")

    try:
        sanitize({"token": "sk_live_1234567890abcdef"}, scanner=broken)
    except SanitizationError as exc:
        assert "detector unavailable" in str(exc)
    else:
        raise AssertionError("sanitizer failure must withhold its input")
    print("PASS  test_sanitizer_failure_is_a_typed_failure_not_unsanitized_output")


def test_tool_result_excerpt_is_bounded_before_persistence():
    event = EvidenceEvent(
        id="e-1", sequence=1, type="tool_result", summary="x" * 1000,
        data={"output": "y" * 1000}, execution_span_id=None,
    )
    safe, omissions = sanitize_event(event, tool_excerpt_limit=64)
    assert len(safe.summary) <= 64
    assert safe.data["output"].endswith("…") and len(safe.data["output"]) == 64
    assert [(omission.category, omission.reason) for omission in omissions] == [
        ("tool_excerpt", "bounded to 64 UTF-8 characters"),
    ]
    print("PASS  test_tool_result_excerpt_is_bounded_before_persistence")


def test_sanitizer_scans_keys_nested_lists_and_three_field_boundaries_and_modern_tokens():
    original = {"sk-proj-abcdefghijklmnop": {"nested": ["sk-", "proj-", "abcdefghijklmnop"], "output": {"deep": "z" * 1000}}}
    safe, redactions = sanitize(original)
    assert "sk-proj" not in repr(safe)
    assert safe["[REDACTED:api_token]"]["nested"] == ["[REDACTED:api_token]", "[REDACTED:api_token]", "[REDACTED:api_token]"]
    assert sum(item.count for item in redactions) >= 2
    event = EvidenceEvent("nested", 1, "tool_result", "ok", {"nested": [{"output": "y" * 1000}]})
    safe_event, omissions = sanitize_event(event, tool_excerpt_limit=64)
    assert safe_event.data["nested"][0]["output"].endswith("…")
    assert omissions
    print("PASS  test_sanitizer_scans_keys_nested_lists_and_three_field_boundaries_and_modern_tokens")


def test_precise_redaction_preserves_unrelated_leaves_and_mapping_cardinality():
    token_a = "sk-proj-Ab_cd-efghijklmnop"
    token_b = "github_pat_abcdefghijk_lmnopqrstuvwxyz0123456789"
    original = {"sha": "a" * 40, token_a: "first", token_b: "second", "prompt": "keep this", "parts": ["sk-proj-Ab_", "cd-efghijklmnop"]}
    safe, _ = sanitize(original)
    assert safe["sha"] == "a" * 40 and safe["prompt"] == "keep this"
    assert len(safe) == len(original)
    assert token_a not in repr(safe) and token_b not in repr(safe)
    assert {"[REDACTED:api_token]", "[REDACTED:api_token]#2"}.issubset(safe)
    assert safe["parts"] == ["[REDACTED:api_token]", "[REDACTED:api_token]"]
    print("PASS  test_precise_redaction_preserves_unrelated_leaves_and_mapping_cardinality")


def test_split_aws_key_and_literal_marker_key_preserve_all_mapping_entries():
    for original in (
        {"[REDACTED:api_token]": "literal", "sk-proj-abcdefghijklmnop": "secret", "access": ["AKIA", "1234567890ABCDEF"]},
        {"sk-proj-abcdefghijklmnop": "secret", "[REDACTED:api_token]": "literal", "access": ["AKIA", "1234567890ABCDEF"]},
    ):
        safe, _ = sanitize(original)
        assert len(safe) == 3 and safe["[REDACTED:api_token]"] == "literal"
        assert safe["[REDACTED:api_token]#2"] == "secret"
        assert safe["access"] == ["[REDACTED:api_token]", "[REDACTED:api_token]"]
    print("PASS  test_split_aws_key_and_literal_marker_key_preserve_all_mapping_entries")


def test_common_credentials_and_private_key_blocks_are_redacted():
    bearer_jwt = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJzdXBlcm1hbiJ9.signature-value"
    private_key = "-----BEGIN PRIVATE KEY-----\nMIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSj\n-----END PRIVATE KEY-----"
    database_url = "postgresql://evidence_user:correct-horse-battery-staple@db.example.invalid:5432/evidence"
    slack_token = "xoxb-123456789012-123456789012-abcdefghijklmnopqrstuvwxyzABCDEF"
    existing = "sk_live_1234567890abcdef github_pat_abcdefghijk_lmnopqrstuvwxyz0123456789 AKIA1234567890ABCDEF"
    original = {"authorization": f"Bearer {bearer_jwt}", "key": private_key,
                "database": database_url, "slack": slack_token, "existing": existing}

    safe, redactions = sanitize(original)

    rendered = repr(safe)
    for credential in (bearer_jwt, private_key, database_url, slack_token, "sk_live_1234567890abcdef", "github_pat_abcdefghijk_lmnopqrstuvwxyz0123456789", "AKIA1234567890ABCDEF"):
        assert credential not in rendered
    assert safe["authorization"] == "[REDACTED:authorization]"
    assert safe["key"] == "[REDACTED:private_key]"
    assert safe["database"] == "[REDACTED:database_url]"
    assert safe["slack"] == "[REDACTED:slack_token]"
    assert {item.category for item in redactions} >= {"api_token", "bearer_token", "private_key", "database_url", "slack_token"}
    print("PASS  test_common_credentials_and_private_key_blocks_are_redacted")


def test_credential_fields_authorization_schemes_and_mapping_boundaries_are_redacted():
    basic = "dXNlcm5hbWU6Y29ycmVjdC1ob3JzZS1iYXR0ZXJ5LXN0YXBsZQ=="
    opaque_bearer = "opaque-bearer-token-value-1234567890"
    short_basic = "YQ=="
    short_bearer = "q7"
    password = "correct-horse-battery-staple"
    token_tail = "1234567890abcdef"
    original = {
        "Authorization": f"Basic {basic}",
        "opaque_header": f"Bearer {opaque_bearer}",
        "short_basic_header": f"Authorization: Basic {short_basic}",
        "short_bearer_header": f"Authorization: Bearer {short_bearer}",
        "database_password": password,
        "client_secret": password,
        "clientSecret": password,
        "dbPassword": password,
        "apiToken": password,
        "key_value_split": {"sk_live_": token_tail},
        "key_key_split": {"sk_live_": "ordinary", token_tail: "ordinary"},
    }

    safe, redactions = sanitize(original)

    rendered = repr(safe)
    for label, credential in {
        "basic": basic, "opaque_bearer": opaque_bearer, "short_basic": short_basic,
        "short_bearer": short_bearer, "password": password, "token_prefix": "sk_live_",
        "token_tail": token_tail,
    }.items():
        assert credential not in rendered, f"{label} survived redaction"
    assert safe["Authorization"] == "[REDACTED:authorization]"
    assert safe["opaque_header"] == "Bearer [REDACTED:bearer_token]"
    assert safe["short_basic_header"] == "Authorization: [REDACTED:authorization]"
    assert safe["short_bearer_header"] == "Authorization: [REDACTED:authorization]"
    assert safe["database_password"] == "[REDACTED:credential]"
    assert safe["client_secret"] == "[REDACTED:credential]"
    assert safe["clientSecret"] == "[REDACTED:credential]"
    assert safe["dbPassword"] == "[REDACTED:credential]"
    assert safe["apiToken"] == "[REDACTED:credential]"
    assert {item.category for item in redactions} >= {"api_token", "authorization", "bearer_token", "credential"}
    print("PASS  test_credential_fields_authorization_schemes_and_mapping_boundaries_are_redacted")


if __name__ == "__main__":
    test_sensitive_token_split_across_ordinary_fields_is_replaced_with_typed_marker()
    test_sanitizer_failure_is_a_typed_failure_not_unsanitized_output()
    test_tool_result_excerpt_is_bounded_before_persistence()
    test_sanitizer_scans_keys_nested_lists_and_three_field_boundaries_and_modern_tokens()
    test_precise_redaction_preserves_unrelated_leaves_and_mapping_cardinality()
    test_split_aws_key_and_literal_marker_key_preserve_all_mapping_entries()
    test_common_credentials_and_private_key_blocks_are_redacted()
    test_credential_fields_authorization_schemes_and_mapping_boundaries_are_redacted()
