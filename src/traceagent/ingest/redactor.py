"""Ingest secret redactor for TraceAgent payloads."""

import re
from typing import Any

REDACTED = "[REDACTED]"

SENSITIVE_KEY_NAMES = frozenset(
    {
        "api_key",
        "apikey",
        "authorization",
        "password",
        "passwd",
        "secret",
        "token",
        "private_key",
        "access_token",
        "refresh_token",
        "client_secret",
        "x-api-key",
        "x_api_key",
    }
)

_SECRET_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"sk-ant-[A-Za-z0-9_-]{16,}"), REDACTED),
    (re.compile(r"sk-(?:proj-)?[A-Za-z0-9_-]{16,}"), REDACTED),
    (re.compile(r"(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}"), REDACTED),
    (re.compile(r"github_pat_[A-Za-z0-9_]{20,}"), REDACTED),
    (re.compile(r"AKIA[0-9A-Z]{16}"), REDACTED),
    (re.compile(r"Bearer\s+[A-Za-z0-9\-._~+/]+=*", re.IGNORECASE), f"Bearer {REDACTED}"),
]


def redact_string(value: str) -> str:
    """Redact known secret patterns from a string."""
    result = value
    for pattern, replacement in _SECRET_PATTERNS:
        result = pattern.sub(replacement, result)
    return result


def redact_secrets(obj: Any) -> Any:
    """Recursively redact secrets from dicts, lists, and strings."""
    if isinstance(obj, str):
        return redact_string(obj)
    if isinstance(obj, dict):
        redacted_dict: dict[str, Any] = {}
        for k, v in obj.items():
            key_str = str(k)
            if key_str.lower() in SENSITIVE_KEY_NAMES:
                redacted_dict[key_str] = REDACTED
            else:
                redacted_dict[key_str] = redact_secrets(v)
        return redacted_dict
    if isinstance(obj, list):
        return [redact_secrets(item) for item in obj]
    if isinstance(obj, tuple):
        return [redact_secrets(item) for item in obj]
    return obj
