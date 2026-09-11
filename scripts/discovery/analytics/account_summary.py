"""Per-account analytics summaries for the dashboard."""

from __future__ import annotations

from typing import Any

from discovery.analytics.refresh import refresh_analytics
from discovery.publishing.credentials import load_credentials
from discovery.publishing.factory import build_publishing_provider
from discovery.store import DiscoveryStore


def fetch_live_account_metrics(store: DiscoveryStore, account_id: int) -> dict[str, Any] | None:
    account = store.get_publishing_account(account_id)
    if not account:
        return None
    try:
        provider = build_publishing_provider(account.platform)
        if not hasattr(provider, "fetch_account_metrics"):
            return None
        creds = load_credentials(account_id)
        if not creds.get("access_token"):
            return None
        metrics = provider.fetch_account_metrics(creds)
        return metrics.to_dict() if hasattr(metrics, "to_dict") else dict(metrics)
    except Exception as exc:
        return {"error": str(exc)}


def owner_analytics_board(
    store: DiscoveryStore,
    *,
    owner: str | None = None,
    include_live: bool = True,
) -> dict[str, Any]:
    accounts = store.list_publishing_accounts(owner=owner, enabled_only=False)
    boards: list[dict[str, Any]] = []
    for account in accounts:
        overview = store.analytics_overview(account_id=account.id)
        posts = store.list_analytics_posts_with_latest(account_id=account.id, limit=8)
        live = fetch_live_account_metrics(store, account.id) if include_live else None
        boards.append(
            {
                "account": {
                    "id": account.id,
                    "owner": account.owner,
                    "platform": account.platform,
                    "display_name": account.display_name,
                    "username": account.username,
                    "auth_status": account.auth_status,
                    "posting_available": account.posting_available,
                },
                "overview": overview,
                "recent_posts": posts,
                "live_metrics": live,
            }
        )
    return {
        "owner": owner,
        "accounts": boards,
        "account_count": len(boards),
    }


def refresh_owner_analytics(
    store: DiscoveryStore,
    *,
    owner: str | None = None,
    limit: int = 50,
    force: bool = False,
) -> dict[str, Any]:
    accounts = store.list_publishing_accounts(owner=owner, enabled_only=True)
    refreshed = 0
    errors = 0
    for account in accounts:
        results = refresh_analytics(store, account_id=account.id, limit=limit, force=force)
        refreshed += sum(1 for r in results if r.refreshed)
        errors += sum(1 for r in results if r.error)
    return {
        "owner": owner,
        "accounts": len(accounts),
        "refreshed": refreshed,
        "errors": errors,
    }
