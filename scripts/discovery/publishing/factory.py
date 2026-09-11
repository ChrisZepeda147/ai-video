"""Build platform publishing provider."""

from __future__ import annotations

import os

from discovery.config import publish_dry_run
from discovery.publishing.base import PublishingProvider
from discovery.publishing.facebook import FacebookPublishingProvider
from discovery.publishing.instagram import InstagramPublishingProvider
from discovery.publishing.mock import MockPublishingProvider
from discovery.publishing.tiktok import TikTokPublishingProvider
from discovery.publishing.youtube import YouTubePublishingProvider


def build_publishing_provider(platform: str) -> PublishingProvider:
    if publish_dry_run() or os.environ.get("DISCOVERY_PUBLISH_PROVIDER", "").strip().lower() == "mock":
        return MockPublishingProvider(platform)
    if platform == "youtube":
        return YouTubePublishingProvider()
    if platform == "tiktok":
        return TikTokPublishingProvider()
    if platform == "instagram":
        return InstagramPublishingProvider()
    if platform == "facebook":
        return FacebookPublishingProvider()
    raise ValueError(f"Unsupported publishing platform: {platform}")
