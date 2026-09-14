"""Instagram / Facebook Reels publish helpers — Graph calls mocked."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from discovery.publishing import facebook, instagram, meta
from discovery.publishing.base import PublishRequest


class MetaReelsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.video = Path(self.tmp.name) / "reel.mp4"
        self.video.write_bytes(b"fake-mp4")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_join_caption_strips_and_limits(self) -> None:
        text = meta.join_caption("Title", "  hook  ", "#cars", limit=14)
        self.assertTrue(text.startswith("Title"))
        self.assertLessEqual(len(text), 14)

    @patch("discovery.publishing.meta.time.sleep", return_value=None)
    @patch("discovery.publishing.meta.graph_get")
    @patch("discovery.publishing.meta.rupload_binary")
    @patch("discovery.publishing.meta.graph_post")
    def test_instagram_resumable_publish(
        self,
        graph_post,
        rupload,
        graph_get,
        _sleep,
    ) -> None:
        graph_post.side_effect = [
            {"id": "17890", "uri": "https://rupload.facebook.com/ig-api-upload/v21.0/17890"},
            {"id": "media99"},
        ]
        rupload.return_value = {"success": True}
        graph_get.side_effect = [
            {"id": "17890", "status_code": "FINISHED"},
            {"id": "media99", "permalink": "https://www.instagram.com/reel/media99/"},
        ]
        result = meta.publish_instagram_reel(
            ig_user_id="ig1",
            token="tok",
            video_path=self.video,
            caption="Drive.",
        )
        self.assertEqual(result["id"], "media99")
        self.assertEqual(result["permalink"], "https://www.instagram.com/reel/media99/")
        create = graph_post.call_args_list[0]
        self.assertEqual(create.args[0], "ig1/media")
        self.assertEqual(create.kwargs["data"]["upload_type"], "resumable")
        rupload.assert_called_once()

    @patch("discovery.publishing.meta.graph_get")
    @patch("discovery.publishing.meta.rupload_binary")
    @patch("discovery.publishing.meta.graph_post")
    def test_facebook_reels_start_upload_finish(self, graph_post, rupload, graph_get) -> None:
        graph_post.side_effect = [
            {"video_id": "vid1", "upload_url": "https://rupload.facebook.com/video-upload/v21.0/vid1"},
            {"success": True},
        ]
        rupload.return_value = {"success": True}
        graph_get.return_value = {"id": "vid1", "permalink_url": "https://www.facebook.com/reel/vid1"}
        result = meta.publish_facebook_reel(
            page_id="page1",
            token="tok",
            video_path=self.video,
            title="Night drive",
            description="Stay focused",
        )
        self.assertEqual(result["id"], "vid1")
        start = graph_post.call_args_list[0].kwargs["data"]
        finish = graph_post.call_args_list[1].kwargs["data"]
        self.assertEqual(start["upload_phase"], "start")
        self.assertEqual(finish["upload_phase"], "finish")
        self.assertEqual(finish["video_state"], "PUBLISHED")

    @patch("discovery.publishing.instagram.meta_api.publish_instagram_reel")
    def test_instagram_provider_uses_user_token(self, publish) -> None:
        publish.return_value = {
            "id": "igmedia",
            "permalink": "https://www.instagram.com/reel/igmedia/",
        }
        provider = instagram.InstagramPublishingProvider()
        result = provider.publish_video(
            {
                "access_token": "user-tok",
                "page_access_token": "page-tok",
                "platform_account_id": "ig1",
            },
            PublishRequest(video_path=str(self.video), title="Title", caption="Hook", hashtags="#cars"),
        )
        self.assertEqual(result.platform_post_id, "igmedia")
        self.assertEqual(publish.call_args.kwargs["token"], "user-tok")

    @patch("discovery.publishing.facebook.meta_api.publish_facebook_reel")
    def test_facebook_provider_uses_page_token(self, publish) -> None:
        publish.return_value = {
            "id": "fbvid",
            "permalink": "https://www.facebook.com/reel/fbvid",
        }
        provider = facebook.FacebookPublishingProvider()
        result = provider.publish_video(
            {"access_token": "user-tok", "page_access_token": "page-tok", "page_id": "page1"},
            PublishRequest(video_path=str(self.video), title="Title", caption="Hook", hashtags="#cars"),
        )
        self.assertEqual(result.platform_post_id, "fbvid")
        self.assertEqual(publish.call_args.kwargs["token"], "page-tok")

    @patch("discovery.publishing.instagram.meta_api.has_publish_permission", return_value=False)
    @patch("discovery.publishing.instagram.meta_api.graph_get")
    def test_instagram_old_scopes_block_posting(self, graph_get, _perm) -> None:
        graph_get.return_value = {"id": "ig1", "username": "luxury"}
        info = instagram.InstagramPublishingProvider().verify_account(
            {"access_token": "tok", "platform_account_id": "ig1"}
        )
        self.assertTrue(info.ok)
        self.assertFalse(info.posting_available)
        self.assertIn("Reconnect", info.audit_note or "")

    def test_instagram_scopes_include_publish(self) -> None:
        self.assertIn("instagram_content_publish", instagram.INSTAGRAM_SCOPES)
        self.assertIn("pages_manage_posts", facebook.FACEBOOK_SCOPES)


if __name__ == "__main__":
    unittest.main()
