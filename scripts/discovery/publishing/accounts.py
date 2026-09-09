"""Connected publishing account management."""

from __future__ import annotations

import json
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from discovery.config import publishing_oauth_states_dir
from discovery.publishing.credentials import delete_credentials, load_credentials, save_credentials
from discovery.publishing.factory import build_publishing_provider


@dataclass
class ConnectStart:
    platform: str
    auth_url: str
    state: str
    instructions: str


def start_account_connect(
    store,
    platform: str,
    *,
    display_name: str,
    niche: str | None = None,
    redirect_uri: str | None = None,
) -> ConnectStart:
    provider = build_publishing_provider(platform)
    state = secrets.token_urlsafe(24)
    default_redirect = redirect_uri or _default_redirect(platform)
    oauth = provider.start_connect(redirect_uri=default_redirect, state=state)
    state_path = publishing_oauth_states_dir() / f"{state}.json"
    verifier = ""
    if platform == "tiktok":
        import sys
        from pathlib import Path as P

        scripts = P(__file__).resolve().parent.parent.parent
        if str(scripts) not in sys.path:
            sys.path.insert(0, str(scripts))
        import tiktok_upload as tt

        verifier, _challenge = tt._pkce_pair()
    state_path.write_text(
        json.dumps(
            {
                "platform": platform,
                "display_name": display_name,
                "niche": niche,
                "redirect_uri": default_redirect,
                "code_verifier": verifier,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return ConnectStart(
        platform=platform,
        auth_url=oauth.auth_url,
        state=state,
        instructions=oauth.instructions,
    )


def complete_account_connect(store, *, state: str, code: str) -> int:
    state_path = publishing_oauth_states_dir() / f"{state}.json"
    if not state_path.is_file():
        raise ValueError("OAuth state expired or invalid")
    state_data = json.loads(state_path.read_text(encoding="utf-8"))
    platform = str(state_data["platform"])
    provider = build_publishing_provider(platform)
    creds = provider.complete_connect(
        redirect_uri=state_data.get("redirect_uri") or _default_redirect(platform),
        code=code,
        state_data=state_data,
    )
    verification = provider.verify_account(creds)
    account_id = store.create_publishing_account(
        platform=platform,
        display_name=state_data.get("display_name") or verification.username or platform,
        platform_account_id=verification.platform_account_id,
        username=verification.username,
        niche=state_data.get("niche"),
        auth_status=verification.auth_status,
        posting_available=verification.posting_available,
        capabilities_json=json.dumps(verification.capabilities),
        audit_note=verification.audit_note,
        token_expires_at=verification.token_expires_at,
    )
    save_credentials(account_id, creds)
    store.update_publishing_account_credentials_ref(account_id, f"account_{account_id:06d}.json")
    state_path.unlink(missing_ok=True)
    return account_id


def import_mock_account(
    store,
    *,
    platform: str,
    display_name: str,
    username: str,
    niche: str | None = None,
) -> int:
    """Dev/test helper — creates a mock-connected account without OAuth."""
    from discovery.publishing.mock import MockPublishingProvider

    provider = MockPublishingProvider(platform)
    creds = provider.complete_connect(
        redirect_uri="http://localhost/callback",
        code="mock",
        state_data={"username": username},
    )
    verification = provider.verify_account(creds)
    account_id = store.create_publishing_account(
        platform=platform,
        display_name=display_name,
        platform_account_id=verification.platform_account_id,
        username=username,
        niche=niche,
        auth_status="connected",
        posting_available=True,
        capabilities_json=json.dumps(verification.capabilities),
    )
    save_credentials(account_id, creds)
    store.update_publishing_account_credentials_ref(account_id, f"account_{account_id:06d}.json")
    return account_id


def verify_publishing_account(store, account_id: int) -> dict[str, Any]:
    account = store.get_publishing_account(account_id)
    if not account:
        raise ValueError(f"Account {account_id} not found")
    provider = build_publishing_provider(account.platform)
    creds = load_credentials(account_id)
    if not creds:
        store.update_publishing_account_status(
            account_id,
            auth_status="disconnected",
            posting_available=False,
        )
        return {"ok": False, "message": "No credentials on disk"}
    try:
        refreshed = provider.refresh_credentials(creds)
        save_credentials(account_id, refreshed)
        creds = refreshed
    except Exception:
        pass
    verification = provider.verify_account(creds)
    store.update_publishing_account_status(
        account_id,
        auth_status=verification.auth_status,
        posting_available=verification.posting_available,
        username=verification.username or account.username,
        platform_account_id=verification.platform_account_id or account.platform_account_id,
        capabilities_json=json.dumps(verification.capabilities),
        audit_note=verification.audit_note,
        token_expires_at=verification.token_expires_at,
        last_verified=True,
    )
    return {
        "ok": verification.ok,
        "username": verification.username,
        "posting_available": verification.posting_available,
        "audit_note": verification.audit_note,
        "message": verification.message,
    }


def disconnect_account(store, account_id: int) -> None:
    delete_credentials(account_id)
    store.update_publishing_account_status(
        account_id,
        auth_status="disconnected",
        posting_available=False,
        enabled=False,
    )


def _default_redirect(platform: str) -> str:
    if platform == "tiktok":
        return "http://127.0.0.1:8787/callback"
    if platform == "youtube":
        return "http://127.0.0.1:8788/callback"
    return "http://127.0.0.1:8790/callback"
