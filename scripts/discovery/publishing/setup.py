"""Publishing OAuth setup status for Settings / preflight."""

from __future__ import annotations

import os
from typing import Any

from discovery.config import publishing_oauth_redirect_uri, publishing_owner
from discovery.store import DiscoveryStore

PLATFORMS = ("youtube", "tiktok", "instagram", "facebook")
OWNERS = ("stephen", "chris")
TARGET_ACCOUNTS_PER_OWNER = 2


def _env_ready(*keys: str) -> bool:
    return all(os.environ.get(key, "").strip() for key in keys)


def _connected(accounts: list[Any]) -> list[Any]:
    return [a for a in accounts if a.auth_status in {"connected", "verified"}]


def publishing_env_status() -> dict[str, Any]:
    mock_provider = os.environ.get("DISCOVERY_PUBLISH_PROVIDER", "").strip().lower() == "mock"
    dry_run = os.environ.get("DISCOVERY_PUBLISH_DRY_RUN", "").strip().lower() in {"1", "true", "yes"}
    redirect = publishing_oauth_redirect_uri()
    return {
        "machine_owner": publishing_owner(),
        "oauth_redirect_uri": redirect,
        "mock_provider": mock_provider,
        "dry_run": dry_run,
        "internal_key_configured": bool(os.environ.get("AI_VIDEO_INTERNAL_KEY", "").strip()),
        "platforms": {
            "youtube": {
                "label": "YouTube",
                "portal_url": "https://console.cloud.google.com/apis/credentials",
                "env_ready": _env_ready("YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET"),
                "env_keys": ["YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET", "YOUTUBE_REDIRECT_URI"],
                "redirect_uri": redirect,
                "notes": "Enable YouTube Data API v3. OAuth client redirect must match exactly.",
            },
            "tiktok": {
                "label": "TikTok",
                "portal_url": "https://developers.tiktok.com/",
                "env_ready": _env_ready("TIKTOK_CLIENT_KEY", "TIKTOK_CLIENT_SECRET"),
                "env_keys": ["TIKTOK_CLIENT_KEY", "TIKTOK_CLIENT_SECRET", "TIKTOK_REDIRECT_URI"],
                "redirect_uri": redirect,
                "notes": "Register Login Kit redirect. Per-video analytics may need extra scopes after connect.",
            },
            "instagram": {
                "label": "Instagram",
                "portal_url": "https://developers.facebook.com/",
                "env_ready": _env_ready("META_APP_ID", "META_APP_SECRET"),
                "env_keys": ["META_APP_ID", "META_APP_SECRET"],
                "redirect_uri": redirect,
                "notes": "Meta app + Instagram Business/Creator linked to a Facebook Page.",
            },
            "facebook": {
                "label": "Facebook",
                "portal_url": "https://developers.facebook.com/",
                "env_ready": _env_ready("META_APP_ID", "META_APP_SECRET"),
                "env_keys": ["META_APP_ID", "META_APP_SECRET"],
                "redirect_uri": redirect,
                "notes": "Same Meta app as Instagram. Connect each Facebook Page separately.",
            },
        },
    }


def publishing_account_matrix(store: DiscoveryStore) -> dict[str, Any]:
    matrix: dict[str, dict[str, dict[str, int]]] = {}
    for owner in OWNERS:
        matrix[owner] = {}
        for platform in PLATFORMS:
            accounts = store.list_publishing_accounts(platform=platform, owner=owner)
            connected = _connected(accounts)
            matrix[owner][platform] = {
                "connected": len(connected),
                "total": len(accounts),
                "target": TARGET_ACCOUNTS_PER_OWNER,
            }
    return matrix


def publishing_setup_report(store: DiscoveryStore | None = None) -> dict[str, Any]:
    env = publishing_env_status()
    matrix = publishing_account_matrix(store) if store else {owner: {} for owner in OWNERS}
    gaps: list[str] = []
    if env["mock_provider"]:
        gaps.append("DISCOVERY_PUBLISH_PROVIDER=mock — real OAuth disabled")
    if not env["internal_key_configured"]:
        gaps.append("AI_VIDEO_INTERNAL_KEY missing — Videos Link post will fail")
    for platform, info in env["platforms"].items():
        if not info["env_ready"]:
            gaps.append(f"{info['label']} app credentials missing in scripts/.env")
    if store:
        for owner in OWNERS:
            for platform in PLATFORMS:
                counts = matrix.get(owner, {}).get(platform, {})
                connected = int(counts.get("connected") or 0)
                target = int(counts.get("target") or TARGET_ACCOUNTS_PER_OWNER)
                if connected < target:
                    gaps.append(
                        f"{owner.title()} {platform}: {connected}/{target} accounts connected"
                    )
    return {
        **env,
        "target_accounts_per_owner": TARGET_ACCOUNTS_PER_OWNER,
        "owners": list(OWNERS),
        "account_matrix": matrix,
        "gaps": gaps,
        "brother_note": (
            "App credentials in scripts/.env can be shared between machines (never commit). "
            "Each brother sets PUBLISHING_OWNER on their PC, then OAuth each social account on /accounts."
        ),
    }
