"""Tests for social post URL parsing."""

from __future__ import annotations

import unittest

from discovery.publishing.platform_urls import parse_platform_post_url


class PlatformUrlTests(unittest.TestCase):
    def test_youtube_watch(self) -> None:
        platform, post_id, url = parse_platform_post_url(
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        )
        self.assertEqual(platform, "youtube")
        self.assertEqual(post_id, "dQw4w9WgXcQ")
        self.assertIn("watch?v=", url)

    def test_tiktok(self) -> None:
        platform, post_id, _url = parse_platform_post_url(
            "https://www.tiktok.com/@user/video/7123456789012345678"
        )
        self.assertEqual(platform, "tiktok")
        self.assertEqual(post_id, "7123456789012345678")

    def test_instagram_reel(self) -> None:
        platform, post_id, _url = parse_platform_post_url(
            "https://www.instagram.com/reel/ABC123xyz/"
        )
        self.assertEqual(platform, "instagram")
        self.assertEqual(post_id, "ABC123xyz")

    def test_facebook_post(self) -> None:
        platform, post_id, _url = parse_platform_post_url(
            "https://www.facebook.com/mypage/posts/1234567890123456"
        )
        self.assertEqual(platform, "facebook")
        self.assertEqual(post_id, "1234567890123456")


if __name__ == "__main__":
    unittest.main()
