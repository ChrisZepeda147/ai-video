"""Parse reuse intent from natural-language production commands."""

from __future__ import annotations

import re

REUSE_POLICIES = frozenset({"allow", "prefer_new", "require_new"})

_REQUIRE_NEW_PATTERNS = (
    r"\buse an unused\b",
    r"\bdo not reuse\b",
    r"\bdon't reuse\b",
    r"\bnever used\b",
    r"\bnot used before\b",
    r"\bfind something we have never used\b",
    r"\bavoid anything previously used\b",
    r"\bavoid previously used\b",
    r"\bonly unused\b",
    r"\brequire new\b",
    r"\bbrand new source\b",
)

_PREFER_NEW_PATTERNS = (
    r"\bprefer new\b",
    r"\bprefer unused\b",
    r"\bfresh material\b",
    r"\bnew material\b",
    r"\btry something new\b",
)


def normalize_reuse_policy(value: str | None, *, default: str = "allow") -> str:
    policy = (value or "").strip().lower().replace("-", "_")
    if policy in REUSE_POLICIES:
        return policy
    return default


def parse_reuse_policy(command: str, explicit: str | None = None) -> str:
    policy = normalize_reuse_policy(explicit, default="")
    if policy:
        return policy
    lower = command.lower()
    for pattern in _REQUIRE_NEW_PATTERNS:
        if re.search(pattern, lower):
            return "require_new"
    for pattern in _PREFER_NEW_PATTERNS:
        if re.search(pattern, lower):
            return "prefer_new"
    return "allow"
