"""RSS dates are publisher dates, never synthesized from the collection clock."""
import contextlib
from datetime import datetime, timezone
import hashlib
import importlib.util
import io
from pathlib import Path
import runpy
import sys
import types
import unittest
from unittest.mock import patch


SOURCE = Path(__file__).resolve().parents[1]


def load_module(name):
    spec = importlib.util.spec_from_file_location(name, SOURCE / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {name: module}):
        spec.loader.exec_module(module)
    return module


timestamp = load_module("rss_timestamp")
policy = load_module("news_collection_policy")
with patch.dict(sys.modules, {"rss_timestamp": timestamp}):
    news = load_module("collect_news")


NOW = datetime(2026, 10, 2, 3, 0, tzinfo=timezone.utc)


class FrozenDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        return NOW.astimezone(tz) if tz else NOW.replace(tzinfo=None)


class RssTimestampTests(unittest.TestCase):
    def test_rfc_utc_converts_across_jst_date_boundary(self):
        self.assertEqual(timestamp.publication_time_jst({
            "published": "Thu, 01 Oct 2026 16:45:00 GMT"
        }), "2026-10-02 01:45:00")

    def test_iso_offset_preserves_actual_instant(self):
        self.assertEqual(timestamp.publication_time_jst({
            "published": "2026-10-01T23:45:00-04:00"
        }), "2026-10-02 12:45:00")

    def test_iso_z_and_fractional_seconds(self):
        self.assertEqual(timestamp.publication_time_jst({
            "published": "2026-10-01T23:00:00.123Z"
        }), "2026-10-02 08:00:00")

    def test_explicit_jst_rfc_zone(self):
        self.assertEqual(timestamp.publication_time_jst({
            "published": "Fri, 02 Oct 2026 09:00:00 JST"
        }), "2026-10-02 09:00:00")

    def test_published_is_preferred_over_updated(self):
        self.assertEqual(timestamp.publication_time_jst({
            "published": "2026-10-01T23:00:00Z",
            "updated": "2026-10-02T03:00:00Z",
        }), "2026-10-02 08:00:00")

    def test_broken_publication_can_use_valid_updated(self):
        self.assertEqual(timestamp.publication_time_jst({
            "published": "broken", "updated": "2026-10-01T14:00:00Z"
        }), "2026-10-01 23:00:00")

    def test_feedparser_parsed_structure_is_utc(self):
        self.assertEqual(timestamp.publication_time_jst({
            "published_parsed": (2026, 10, 1, 22, 30, 0, 3, 274, 0)
        }), "2026-10-02 07:30:00")

    def test_parsed_updated_fallback(self):
        self.assertEqual(timestamp.publication_time_jst({
            "published_parsed": (2026, 99, 1, 0, 0, 0),
            "updated_parsed": (2026, 10, 2, 0, 0, 0),
        }), "2026-10-02 09:00:00")

    def test_broken_or_ambiguous_raw_date_is_not_rescued_by_parser_guess(self):
        for value in ("broken", "2026-10-02T03:00:00"):
            self.assertIsNone(timestamp.publication_time({
                "published": value, "published_parsed": (2026, 10, 2, 3, 0, 0)
            }))

    def test_missing_broken_or_ambiguous_dates_are_rejected(self):
        for entry in ({}, {"published": None}, {"published": "broken"},
                      {"published": "2026-10-02T03:00:00"},
                      {"published": "Fri, 02 Oct 2026 03:00:00"},
                      {"published": "Fri, 02 Oct 2026 03:00:00 XYZ"},
                      {"published_parsed": (2026, 13, 2, 0, 0, 0)},
                      {"published_parsed": "2026-10-02"}):
            with self.subTest(entry=entry):
                self.assertIsNone(timestamp.publication_time(entry))

    def test_xml_published_and_updated_contracts(self):
        xml = """<rss xmlns:atom="http://www.w3.org/2005/Atom"
                xmlns:dc="http://purl.org/dc/elements/1.1/"><channel>
        <item><title>Nikkei one</title><link>https://example.test/1</link>
          <pubDate>Fri, 02 Oct 2026 00:00:00 GMT</pubDate></item>
        <item><title>Nikkei two</title><link>https://example.test/2</link>
          <pubDate>invalid</pubDate><atom:updated>2026-10-02T01:30:00Z</atom:updated></item>
        <item><title>Nikkei three</title><link>https://example.test/3</link></item>
        <item><title>Nikkei four</title><link>https://example.test/4</link>
          <pubDate>invalid</pubDate><updated>invalid</updated></item>
        <item><title>Nikkei five</title><link>https://example.test/5</link>
          <dc:date>2026-10-02T02:30:00Z</dc:date></item>
        <item><title>Nikkei stale</title><link>https://example.test/6</link>
          <pubDate>Wed, 30 Sep 2026 00:00:00 GMT</pubDate></item>
        </channel></rss>"""
        with patch.object(news, "datetime", FrozenDateTime):
            items = news._parse_rss(xml, "nhk_biz")
        self.assertEqual([item["published_at"] for item in items], [
            "2026-10-02 09:00:00", "2026-10-02 10:30:00", "2026-10-02 11:30:00"
        ])
        self.assertEqual([item["age_min"] for item in items], [180, 90, 30])
        self.assertEqual(items[0]["uid"], hashlib.md5(b"nhk_biz:Nikkei one").hexdigest()[:16])
        self.assertEqual(items[0]["source"], "nhk_biz")
        self.assertEqual(items[0]["score"], 2)

    def test_xml_z_date_ignores_collector_local_timezone(self):
        xml = """<rss><channel><item><title>Nikkei</title><link>https://example.test/1</link>
            <pubDate>2026-10-02T02:00:00Z</pubDate></item></channel></rss>"""
        with patch.object(news, "datetime", FrozenDateTime):
            item = news._parse_rss(xml, "nhk_biz")[0]
        self.assertEqual(item["published_at"], "2026-10-02 11:00:00")
        self.assertEqual(item["age_min"], 60)

    def _run_worker(self, feeds, response_status=200):
        import feedparser
        import requests
        captured = []
        common = types.ModuleType("collector_common")
        common.push_json = lambda base, path, payload, **kwargs: (
            captured.append((path, payload)) or {"ok": True, "saved": len(payload["items"])}
        )
        response = types.SimpleNamespace(status_code=response_status, text="mock RSS")
        with patch.dict(sys.modules, {"collector_common": common, "rss_timestamp": timestamp,
                                    "news_collection_policy": policy}), \
             patch.object(policy, "datetime", FrozenDateTime), \
             patch.object(requests, "get", return_value=response), \
             patch.object(feedparser, "parse", side_effect=feeds), \
             patch("time.sleep"), contextlib.redirect_stdout(io.StringIO()):
            runpy.run_path(str(SOURCE / "fetch_news_worker.py"), run_name="rss_worker_test")
        return captured

    def test_worker_skips_bad_dates_but_keeps_contract_and_valid_duplicate(self):
        entries = [
            {"title": "Toyota earnings primary", "link": "https://example.test/primary", "published": "2026-10-01T22:00:00Z",
             "updated": "2026-10-02T02:00:00Z"},
            {"title": "Toyota earnings updated", "link": "https://example.test/updated", "published": "bad", "updated": "2026-10-01T23:00:00Z"},
            {"title": "Toyota earnings missing"},
            {"title": "Toyota earnings broken", "published": "bad"},
            {"title": "Toyota earnings repeat", "link": "https://example.test/repeat", "published": "bad"},
            {"title": "Toyota earnings repeat", "link": "https://example.test/repeat", "published_parsed": (2026, 10, 2, 0, 0, 0)},
        ]
        feeds = [types.SimpleNamespace(bozo=False, entries=entries)]
        feeds += [types.SimpleNamespace(bozo=False, entries=[]) for _ in range(4)]
        captured = self._run_worker(feeds)
        self.assertEqual(len(captured), 1)
        path, payload = captured[0]
        self.assertEqual(path, "/push/news")
        self.assertEqual([item["published_at"] for item in payload["items"]], [
            "2026-10-02 07:00:00", "2026-10-02 08:00:00", "2026-10-02 09:00:00"
        ])
        self.assertEqual(payload["items"][0]["uid"], policy.news_uid(
            "https://example.test/primary", "Toyota earnings primary", "2026-10-02 07:00:00"))
        self.assertTrue(all(item["source"] == "nhk_eco" and item["score"] == 1.0
                            for item in payload["items"]))

    def test_worker_all_source_failures_remain_failures(self):
        with self.assertRaisesRegex(RuntimeError, "All RSS sources failed"):
            self._run_worker([], response_status=503)


if __name__ == "__main__":
    unittest.main()
