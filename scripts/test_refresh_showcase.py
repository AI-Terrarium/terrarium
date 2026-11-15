from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image
from i18n import page_path

from heat import Source, collect_one, fetch_metrics, rank_entries, source_for_url, source_refs
from refresh_showcase import Entry, ROOT, attach_engagement_links, build, load_catalog, recent_entries, select_entries, showcase_markup


NOW = datetime(2026, 11, 16, 12, tzinfo=timezone.utc)


def entry(title="Example", url="https://x.com/creator/status/123", **kwargs):
    return Entry(title, url, "Creator", "games", **kwargs)


def snapshot(sources=None, stamp="2026-11-16T12:00:00Z"):
    return {"schema_version": 1, "updated_at": stamp, "method": "public-support-v1",
            "sources": sources or {}, "unavailable": []}


def record(platform, metrics, age=1):
    return {"platform": platform, "metrics": metrics, "url": "https://example.com/source",
            "published_at": (NOW - timedelta(days=age)).isoformat()}


class HeatTests(unittest.TestCase):
    def test_x_embed_keeps_unavailable_views_and_shares_missing(self):
        with patch.dict(os.environ, {"X_BEARER_TOKEN": ""}):
            result = collect_one(Source("x", "123", "https://x.com/i/status/123"), lambda _: {
                "created_at": "2026-11-15T12:00:00Z", "favorite_count": 100, "conversation_count": 4,
            })
        self.assertEqual(result["metrics"], {"likes": 100, "comments": 4})
        self.assertNotIn("views", result["metrics"])

    def test_bilibili_collects_all_public_engagement_signals(self):
        result = collect_one(Source("bilibili", "BVabc", "https://www.bilibili.com/video/BVabc/"), lambda _: {
            "code": 0, "data": {"pubdate": int(NOW.timestamp()), "stat": {
                "view": 1000, "like": 20, "reply": 3, "share": 2, "favorite": 4, "coin": 5,
            }},
        })
        self.assertEqual(result["metrics"], {"views": 1000, "likes": 20, "comments": 3,
                                             "shares": 2, "favorites": 4, "coins": 5})

    def test_support_counts_determine_order_while_views_are_separate(self):
        sources = {
            "x:1": record("x", {"likes": 2000, "views": 10000}),
            "bilibili:BVabc": record("bilibili", {"likes": 20, "views": 100000000}),
            "huggingface:person/top": record("huggingface", {"likes": 1000}),
        }
        entries = [entry("X winner", "https://x.com/person/status/1"),
                   entry("Many views", "https://www.bilibili.com/video/BVabc/"),
                   entry("HF winner", "https://huggingface.co/spaces/person/top")]
        ranked = rank_entries(entries, snapshot(sources))
        self.assertEqual([row[0].title for row in ranked], ["X winner", "HF winner", "Many views"])
        self.assertEqual([row[1] for row in ranked], [2000, 1000, 20])

    def test_strong_support_is_not_penalized_for_an_older_publication(self):
        sources = {"x:1": record("x", {"likes": 7500}, age=1),
                   "x:2": record("x", {"likes": 14800}, age=30),
                   "x:3": record("x", {"likes": 999999}, age=-1)}
        entries = [entry("New", "https://x.com/a/status/1"), entry("Old", "https://x.com/a/status/2"),
                   entry("Future", "https://x.com/a/status/3")]
        ranked = rank_entries(entries, snapshot(sources))
        self.assertEqual([row[0].title for row in ranked], ["Old", "New"])
        self.assertGreater(ranked[0][1], ranked[1][1])

    def test_quiet_platform_leader_cannot_displace_strong_public_interest(self):
        sources = {"x:123": record("x", {"likes": 2000, "comments": 100}),
                   "bilibili:BVabc": record("bilibili", {"views": 180, "likes": 4, "comments": 1})}
        ranked = rank_entries([entry("Popular"), entry("Quiet", "https://www.bilibili.com/video/BVabc/")],
                              snapshot(sources))
        self.assertEqual(ranked[0][0].title, "Popular")
        self.assertGreater(ranked[0][1], ranked[1][1] * 5)

    def test_duplicate_publication_is_shown_once(self):
        sources = {"x:123": record("x", {"likes": 100}),
                   "huggingface:person/work": record("huggingface", {"likes": 1})}
        ranked = rank_entries([entry("First"), entry("Second")], snapshot(sources))
        self.assertEqual(len(ranked), 1)

    def test_available_support_can_rank_even_if_other_platforms_are_unavailable(self):
        state = snapshot({"x:123": record("x", {"likes": 1000})})
        selected, ranked = select_entries([entry()], [entry("Recent release")], state)
        self.assertTrue(ranked)
        self.assertEqual(selected[0].title, "Example")

    def test_playable_work_keeps_its_independent_social_post_in_the_candidate_pool(self):
        work = entry("Popular game", "https://play.example.com/", social_urls=("https://x.com/creator/status/999",))
        self.assertIn("x:999", source_refs(work))
        state = snapshot({"x:999": record("x", {"likes": 17887}),
                          "x:123": record("x", {"likes": 7516})})
        ranked = rank_entries([work, entry("Lower support")], state)
        self.assertEqual(ranked[0][0], work)
        self.assertEqual(ranked[0][1], 17887)

    def test_multiple_posts_on_one_platform_do_not_stack_support(self):
        work = entry("Two posts", social_urls=("https://x.com/creator/status/999",))
        state = snapshot({"x:123": record("x", {"likes": 100}),
                          "x:999": record("x", {"likes": 80}),
                          "x:555": record("x", {"likes": 110})})
        ranked = rank_entries([work, entry("More loved", "https://x.com/a/status/555")], state)
        self.assertEqual([row[1] for row in ranked], [110, 100])

    def test_known_high_support_games_have_their_original_posts_attached(self):
        entries, _ = load_catalog(ROOT)
        expected = {"Starry Nightrider": "x:2120284261089673376", "Saltline": "x:2119925633564463609",
                    "Oil paint": "x:2120341251178594532"}
        for name, key in expected.items():
            work = next(item for item in entries if item.title == name)
            self.assertIn(key, source_refs(work), name)

    def test_independent_platform_evidence_contributes_to_same_work(self):
        sources = {"x:123": record("x", {"likes": 100}),
                   "github:person/work": record("github", {"stars": 10, "forks": 1})}
        work = entry(code="https://github.com/person/work")
        combined = rank_entries([work], snapshot(sources))[0]
        x_only = rank_entries([entry()], snapshot(sources))[0]
        self.assertGreater(combined[1], x_only[1])
        self.assertEqual(len(combined[2]), 2)

    def test_one_failed_platform_does_not_erase_valid_public_counters(self):
        entries = [entry(), entry("HF", "https://huggingface.co/spaces/person/work")]

        def get(url):
            if "syndication" in url:
                raise OSError("API unavailable")
            return {"createdAt": "2026-11-15T12:00:00Z", "likes": 3}

        with patch.dict(os.environ, {"X_BEARER_TOKEN": ""}):
            result = fetch_metrics(entries, NOW, get)
        self.assertIn("huggingface:person/work", result["sources"])
        self.assertNotIn("x:123", result["sources"])
        self.assertEqual(result["unavailable"], [{"source": "x:123", "reason": "OSError"}])

    def test_total_outage_cannot_publish_a_fresh_snapshot(self):
        with patch.dict(os.environ, {"X_BEARER_TOKEN": ""}):
            with self.assertRaisesRegex(RuntimeError, "previous showcase retained"):
                fetch_metrics([entry()], NOW, lambda _: {})

    def test_repository_paths_and_shared_video_urls_deduplicate(self):
        self.assertEqual(source_for_url("https://github.com/Owner/Repo/blob/main/index.html").key,
                         "github:owner/repo")
        self.assertEqual(source_for_url("https://github.com/Owner/Repo.git").key, "github:owner/repo")
        self.assertIsNone(source_for_url("https://github.com/Owner"))
        self.assertIsNone(source_for_url("https://github.com.evil.example/Owner/Repo"))


class ShowcaseTests(unittest.TestCase):
    def test_pending_state_exposes_no_fake_heat_or_sync_date(self):
        state = snapshot(stamp=None)
        markup = showcase_markup([entry()], [entry()], False, state, "2026-11-14", NOW)
        self.assertIn("First sync pending", markup)
        self.assertIn("Catalog data: 2026-11-14", markup)
        self.assertNotIn("Heat 0.0", markup)
        self.assertNotIn("Updated:", markup)

    def test_old_snapshot_is_marked_in_both_languages(self):
        state = snapshot(stamp="2026-11-14T12:00:00Z")
        english = showcase_markup([entry()], [entry()], False, state, "2026-11-14", NOW)
        chinese = showcase_markup([entry()], [entry()], False, state, "2026-11-14", NOW, True)
        self.assertIn("snapshot over 12 hours old", english.lower())
        self.assertIn("快照已超过 12 小时", chinese)
        self.assertIn("2026-11-14 12:00 UTC", english)

    def prepare_root(self, root):
        for category in ("games", "videos", "scenes", "wallpapers", "tools", "visualizations"):
            (root / category).mkdir()
            (root / category / "README.md").write_text((ROOT / category / "README.md").read_text())
        for name in (page_path("en"), page_path("zh-CN")):
            (root / name).parent.mkdir(parents=True, exist_ok=True)
            (root / name).write_text((ROOT / name).read_text())
        (root / "assets").mkdir()

    def test_offline_fallback_produces_a_real_loop_and_static_alternative(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.prepare_root(root)
            entries, date = load_catalog(root)
            for item in recent_entries(root, entries):
                target = root / item.thumbnail
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes((ROOT / item.thumbnail).read_bytes())
            build(root, snapshot(stamp=None), NOW)
            with Image.open(root / "assets/showcase.gif") as animation:
                self.assertEqual(animation.n_frames, 4)
                self.assertEqual(animation.info["loop"], 0)
            with Image.open(root / "assets/showcase.webp") as still:
                self.assertEqual(still.size, (1200, 450))
            self.assertIn(date, (root / page_path("zh-CN")).read_text())

    def test_invalid_markers_leave_existing_assets_and_readmes_untouched(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.prepare_root(root)
            english = (root / "README.md").read_text()
            (root / page_path("zh-CN")).write_text("missing markers")
            (root / "assets/showcase.gif").write_bytes(b"previous image")
            with self.assertRaisesRegex(ValueError, "SHOWCASE marker"):
                build(root, snapshot(stamp=None), NOW)
            self.assertEqual((root / "README.md").read_text(), english)
            self.assertEqual((root / "assets/showcase.gif").read_bytes(), b"previous image")


if __name__ == "__main__":
    unittest.main()
