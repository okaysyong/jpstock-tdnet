"""Offline candidate acceptance, dates, and source identity regressions."""
from datetime import datetime, timedelta, timezone
import importlib.util
from pathlib import Path
import unittest

SOURCE = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("isolated_news_policy", SOURCE / "news_collection_policy.py")
policy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(policy)
NOW = datetime(2026, 10, 3, 0, 0, tzinfo=timezone.utc)


class NewsCollectionPolicyTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
