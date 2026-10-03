"""Offline candidate acceptance, dates, and source identity regressions."""
from datetime import datetime, timedelta, timezone
import contextlib
import importlib.util
import io
from pathlib import Path
import runpy
import sys
import types
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("isolated_news_policy", SOURCE / "news_collection_policy.py")
policy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(policy)
NOW = datetime(2026, 10, 3, 0, 0, tzinfo=timezone.utc)


class NewsCollectionPolicyTests(unittest.TestCase):
    def test_official_feed_identity_is_bound_to_article_host_not_title_claims(self):
        title = '通期業績予想の修正について'
        self.assertEqual(policy.relevance(title, source_url='https://global.toyota/jp/ir/1')[1], ['7203'])
        for url in ('https://global.toyota.fake.test/ir/1', 'https://global.toyota@fake.test/ir/1'):
            self.assertEqual(policy.relevance(title, source_url=url)[0], 'no_verified_japan_equity_link')
        self.assertEqual(policy.relevance('週末のドライブ特集', source_url='https://global.toyota/news/1')[0],
                         'no_verified_japan_equity_link')

    def test_official_macro_can_be_identified_without_redundant_organisation_in_title(self):
        self.assertEqual(policy.relevance('金融政策決定会合における主な意見',
            source_url='http://www.boj.or.jp/mopo/1.htm')[0], 'official_japan_market_fact')
        self.assertEqual(policy.relevance('売買停止について', source_url='https://www.jpx.co.jp/news/1')[0],
                         'official_japan_market_fact')
        self.assertEqual(policy.article_url('http://www.boj.or.jp/mopo/1.htm'), 'https://www.boj.or.jp/mopo/1.htm')
        self.assertEqual(policy.article_url('http://example.test/1'), 'http://example.test/1')

    def test_syndicated_original_publisher_is_preserved(self):
        self.assertEqual(policy.publisher_name({'source': {'title': 'ロイター'}}, 'yahoo_biz'), 'ロイター')
        self.assertEqual(policy.publisher_name({}, 'yahoo_biz'), 'yahoo_biz')

    def test_issuer_events_keep_precise_codes_without_inferring_causes(self):
        cases = [
            ("トヨタ、通期の営業利益予想を上方修正", ["7203"]),
            ("Sony raises annual profit forecast", ["6758"]),
            ("メルカリ、売上高が増加", ["4385"]),
            ("任天堂、映画関連の売上高が増加", ["7974"]),
            ("SCREEN、通期業績予想を下方修正", ["7735"]),
            ("SoftBank Group reports earnings", ["9984"]),
            ("SoftBank Corp reports earnings", ["9434"]),
            ("トヨタと日産が生産提携を発表", ["7201", "7203"]),
        ]
        for title, codes in cases:
            with self.subTest(title=title):
                reason, found = policy.relevance(title)
                self.assertNotEqual(reason, "no_verified_japan_equity_link")
                self.assertEqual(found, codes)

    def test_generic_foreign_market_words_and_lifestyle_do_not_admit_a_story(self):
        for title in (
            "AI chip shares rally after earnings", "US stocks rally", "Taiwan election result",
            "Oil price falls", "Toyota baseball team wins", "トヨタの車で旅行へ",
            "ソニーの映画が人気", "日本の有名人が投資を語る", "雇用統計を発表",
            "Sonyville raises profit forecast", "screen factory earnings in Europe",
            "SoftBank earnings announced", "中国大使館侵入事件 元自衛官が無罪主張",
        ):
            with self.subTest(title=title):
                self.assertEqual(policy.relevance(title), ("no_verified_japan_equity_link", []))

    def test_japan_macro_requires_both_subject_and_concrete_market_event(self):
        for title in ("日銀、政策金利を据え置き", "Bank of Japan announces monetary policy",
                      "日本のGDPが前期比で増加", "TOPIXが下落", "円相場が円高に進む"):
            with self.subTest(title=title):
                self.assertEqual(policy.relevance(title), ("japan_market_fact", []))
        for title in ("日銀の博物館へ行こう", "日本の週末観光", "TOPIXとは何か",
                      "Bank of Japan museum opens"):
            self.assertEqual(policy.relevance(title)[0], "no_verified_japan_equity_link")

    def test_registry_extension_rejects_short_ambiguous_alias(self):
        self.assertEqual(policy.relevance("Hotel profits rise", {"8035": ["TEL"]})[0],
                         "no_verified_japan_equity_link")
        self.assertEqual(policy.relevance("架空産業の業績修正", {"1234": ["架空産業"]})[1], ["1234"])

    def test_dates_preserve_original_instant_and_refuse_bad_or_future_time(self):
        self.assertEqual(policy.publication_time({"published": "2026-10-02T20:30:00+09:00"}, NOW),
                         datetime(2026, 10, 2, 11, 30, tzinfo=timezone.utc))
        for entry in ({}, {"published": "bad"}, {"published": "2026-10-02T20:30:00"},
                      {"published": "2026-10-04T00:00:00Z", "updated": "2026-10-02T00:00:00Z"},
                      {"published": "2026-08-01T00:00:00Z"}):
            with self.subTest(entry=entry):
                self.assertIsNone(policy.publication_time(entry, NOW))

    def test_missing_date_can_use_publisher_updated_but_not_parser_guess(self):
        self.assertEqual(policy.publication_time({"updated": "2026-10-02T00:00:00Z"}, NOW),
                         NOW - timedelta(days=1))
        self.assertIsNone(policy.publication_time({"published": "bad",
                         "published_parsed": (2026, 10, 2, 0, 0, 0)}, NOW))

    def test_normalizes_only_known_legacy_ranks(self):
        for value, expected in ((0, 0), (0.8, 0.8), (1, 1), (2, .5), (3, .75), (4, 1),
                                (99, 0), (-1, 0), (float("nan"), 0)):
            self.assertEqual(policy.normalize_score(value), expected)

    def test_url_tracking_variants_collapse_but_article_queries_remain(self):
        a = "https://NEWS.example/a?id=123&utm_source=rss#top"
        b = "https://news.example/a?id=123&fbclid=abc"
        self.assertEqual(policy.news_identity(a, "企業の決算", "2026-10-02 10:00:00"),
                         policy.news_identity(b, "企業の決算", "2026-10-02 10:00:00"))
        self.assertNotEqual(policy.news_identity(a, "企業の決算", "2026-10-02 10:00:00"),
                            policy.news_identity(b.replace("123", "124"), "企業の決算", "2026-10-02 10:00:00"))

    def test_corrections_changed_titles_and_revised_dates_are_not_merged(self):
        base = ("https://news.example/a", "トヨタ 決算", "2026-10-02 10:00:00")
        original = policy.news_identity(*base)
        self.assertNotEqual(original, policy.news_identity(base[0], "訂正 トヨタ 決算", base[2]))
        self.assertNotEqual(original, policy.news_identity(base[0], base[1], "2026-10-02 10:05:00"))
        self.assertNotEqual(original, policy.news_identity(base[0] + "?revision=2", *base[1:]))

    def test_unusable_or_credential_urls_are_rejected(self):
        for url in ("", "javascript:alert(1)", "https://user:pass@example.test/a", "/relative"):
            self.assertEqual(policy.news_identity(url, "title", "date"), "")

    def test_active_worker_collects_primary_candidates_and_keeps_original_publisher(self):
        import requests
        import feedparser
        stamp = "2026-10-02T00:00:00Z"
        feeds = {
            "https://www.jpx.co.jp/rss/markets_news.xml": [dict(title="取引制度の変更について", link="https://www.jpx.co.jp/news/market/1.html", published=stamp)],
            "https://www.boj.or.jp/rss/whatsnew.xml": [dict(title="当面の金融政策運営について", link="http://www.boj.or.jp/mopo/outlook/sample.htm", published=stamp)],
            "https://global.toyota/export/jp/allnews_rss.xml": [dict(title="2027年3月期の業績予想を修正", link="https://global.toyota/jp/newsroom/corporate/1.html", published=stamp)],
            "https://news.yahoo.co.jp/rss/categories/business.xml": [dict(title="Toyota raises profit forecast", link="https://news.yahoo.co.jp/articles/one", published=stamp, source={"title": "Reuters"})],
        }
        captured = []
        common = types.SimpleNamespace(push_json=lambda base, path, payload, **kwargs: captured.extend(payload["items"]) or {"saved": len(payload["items"])})
        with patch.dict(sys.modules, {"collector_common": common, "news_collection_policy": policy}), \
             patch.object(requests, "get", side_effect=lambda url, **kwargs: types.SimpleNamespace(status_code=200, text=url)), \
             patch.object(feedparser, "parse", side_effect=lambda raw: types.SimpleNamespace(bozo=False, entries=feeds.get(raw, []))), \
             patch("time.sleep"), contextlib.redirect_stdout(io.StringIO()):
            runpy.run_path(str(SOURCE / "fetch_news_worker.py"), run_name="offline_primary_worker")
        self.assertEqual(len(captured), 4)
        by_source = {row["source"]: row for row in captured}
        self.assertEqual(by_source["Reuters"]["stocks"], ["7203"])
        self.assertEqual(by_source["toyota_official"]["stocks"], ["7203"])
        self.assertTrue(by_source["boj_official"]["url"].startswith("https://www.boj.or.jp/"))
        self.assertTrue(all(row["published_at"] == "2026-10-02 09:00:00" for row in captured))


if __name__ == "__main__":
    unittest.main()
