"""Publishing provider interface — not locked to one platform."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class AccountVerification:
    ok: bool
    username: str | None = None
    platform_account_id: str | None = None
    posting_available: bool = False
    auth_status: str = "connected"
    capabilities: dict[str, Any] = field(default_factory=dict)
    audit_note: str | None = None
    token_expires_at: str | None = None
    message: str | None = None


@dataclass
class PublishRequest:
    video_path: str
    title: str
    caption: str = ""
    hashtags: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class PublishResult:
    platform_post_id: str
    platform_url: str | None
    status: str
    processing_status: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class OAuthStart:
    auth_url: str
    state: str
    instructions: str = ""


class PublishingProvider(Protocol):
    platform: str

    def start_connect(self, *, redirect_uri: str, state: str) -> OAuthStart: ...

    def complete_connect(self, *, redirect_uri: str, code: str, state_data: dict[str, Any]) -> dict[str, Any]: ...

    def refresh_credentials(self, credentials: dict[str, Any]) -> dict[str, Any]: ...

    def verify_account(self, credentials: dict[str, Any]) -> AccountVerification: ...

    def publish_video(self, credentials: dict[str, Any], request: PublishRequest) -> PublishResult: ...

    def fetch_publish_status(
        self, credentials: dict[str, Any], platform_post_id: str
    ) -> dict[str, Any]: ...
