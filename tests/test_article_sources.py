"""Publication times and actual financial claims stay tied to source articles."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import collector_parsing as parsing
import collect_stock_news as stock_news
import collect_kabutan as kabutan
import fetch_kessan as kessan


class Page:
    status_code = 200
    def __init__(self, text):
        self.text = text
    def raise_for_status(self):
        pass


OLD_ARTICLE = '''<table class="s_news_list"><tr>
  <td><time datetime="2026-10-01T15:02:47+09:00">10/01 15:02</time></td>
  <td><a href="/stock/?code=646A">646A</a></td>
  <td><a href="/news/marketnews/?&amp;b=n202610010463">新会社は上方修正を発表</a></td>
</tr></table>'''


class ArticleSources(unittest.TestCase):
    def test_old_news_retains_publication_day_clock_and_new_code(self):
        items = stock_news._parse_news_list(OLD_ARTICLE, 'kabutan_stock')
        self.assertEqual(len(items), 1)
        self.assertEqual((items[0]['date'], items[0]['time'], items[0]['code']),
                         ('2026-10-01', '15:02', '646A'))
        # The former fallback erased valid rows when the page had fewer than 5.
        self.assertIn('b=n202610010463', items[0]['url'])

    def test_same_article_keeps_identity_across_fetch_days(self):
        with patch.object(stock_news, '_today', return_value='2026-10-02'):
            first = stock_news._parse_news_list(OLD_ARTICLE, 'kabutan_stock')[0]
        with patch.object(stock_news, '_today', return_value='2026-10-03'):
            second = stock_news._parse_news_list(OLD_ARTICLE, 'kabutan_stock')[0]
        self.assertEqual(first['id'], second['id'])

    def test_datetime_is_converted_to_japanese_time(self):
        html = OLD_ARTICLE.replace('2026-10-01T15:02:47+09:00', '2026-10-01T23:02:47Z')
        article = next(parsing.kabutan_articles(html))
        self.assertEqual(article['published_at'], '2026-10-02 08:02:47')

    def test_dated_document_fallback_uses_sequence_as_identity_not_time(self):
        html = '''<tr><td>10/01 15:02</td><td><a href="/news/marketnews/?b=n202610010463">記事本文と重要なニュース</a></td></tr>'''
        article = next(parsing.kabutan_articles(html))
        self.assertEqual(article['published_at'], '2026-10-01 15:02:00')

    def test_unknown_time_or_invalid_source_date_does_not_become_current_news(self):
        for html in (
            '<tr><td>15:02</td><td><a href="/news/item12345">上方修正を発表</a></td></tr>',
            OLD_ARTICLE.replace('2026-10-01T15:02:47+09:00', 'invalid').replace('20261001', '20260230'),
        ):
            self.assertEqual(stock_news._parse_news_list(html, 'kabutan_stock'), [])

    def test_japanese_codes_accept_digits_or_three_digits_and_letter_only(self):
        for code in ('7203', '285A', '646A'):
            self.assertEqual(parsing.stock_code('/stock/?code=' + code), code)
        for code in ('285', '72030', '7203A', 'ABC1'):
            self.assertEqual(parsing.stock_code('/stock/?code=' + code), '')

    def test_rankings_are_never_manufactured_into_guidance_or_rating_articles(self):
        with patch.object(kabutan.SESSION, 'get') as get:
            self.assertEqual(kabutan.fetch_gyoseki_correction(), [])
            self.assertEqual(kabutan.fetch_rating(), [])
            self.assertEqual(kabutan.fetch_stop_stocks(), [])
            get.assert_not_called()

    def test_kabutan_news_retains_time_and_score_accepted_by_ingestion(self):
        with patch.object(kabutan.SESSION, 'get', return_value=Page(OLD_ARTICLE)):
            items = kabutan.fetch_news_market()
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]['published_at'], '2026-10-01 15:02:47')
        self.assertEqual(items[0]['stocks'], ['646A'])
        # The strict VPS News contract reads score, not the old ignored importance.
        self.assertEqual(items[0]['score'], 3)
        self.assertEqual(items[0]['source'], 'kabutan_news')

    def test_valid_source_without_important_articles_is_a_successful_empty_run(self):
        html = OLD_ARTICLE.replace('新会社は上方修正を発表', '明日の予定を公開します')
        with patch.object(kabutan.SESSION, 'get', return_value=Page(html)) as get, \
                patch.object(kabutan, 'push_to_vps') as push:
            kabutan.main()
        self.assertEqual(get.call_count, 1)
        push.assert_not_called()

    def test_unparseable_sources_fail_instead_of_reporting_successful_empty_run(self):
        with patch.object(kabutan.SESSION, 'get', return_value=Page('<html>Unavailable</html>')), \
                patch.object(kabutan.time, 'sleep'), self.assertRaises(RuntimeError):
            kabutan.main()

    def test_minkabu_does_not_borrow_adjacent_article_or_page_clock(self):
        html = '''<time datetime="2026-10-02T11:00+09:00"></time>
          <div><article><a href="/news/123">新会社は上方修正を発表</a></article>
          <article><a href="/news/456">旧会社は決算を発表</a><time datetime="2026-10-01T15:00+09:00"></time></article></div>'''
        with patch.object(kabutan.SESSION, 'get', return_value=Page(html)):
            items = kabutan.fetch_minkabu_news()
        self.assertEqual(len(items), 1)
        self.assertTrue(items[0]['url'].endswith('/456'))
        self.assertEqual(items[0]['published_at'], '2026-10-01 15:00:00')

    def test_earnings_schedule_includes_alphanumeric_security_code(self):
        html = '''<section class="result" id = "stocklist"><table>
          <tr><th>銘柄名</th><th>決算発表(予定)</th></tr>
          <tr><td><a href="/reportTop?bcode=285A"><p>日本の新会社</p></a></td>
            <td>2026/10/02</td><td>2026/09</td><td>2Q</td></tr>
          <tr><td><a href="/reportTop?bcode=7203"><p>トヨタ</p></a></td>
            <td>2026/10/02</td><td>2026/09</td><td>本決算</td></tr>
          </table></section>'''
        with patch.object(kessan.requests, 'get', return_value=Page(html)):
            items = kessan.fetch_kabuyoho_date('2026-10-02')
        self.assertEqual([item['code'] for item in items], ['285A', '7203'])
        self.assertEqual([item['fiscal_period'] for item in items], ['2Q', '本決算'])

    def test_kabutan_earnings_document_and_data_code_keep_source_day(self):
        html = '''<table class="s_news_list"><tr>
          <td><time datetime="2026-10-01T15:30:00+09:00">10/01 15:30</time></td>
          <td data-code="646A">決算</td>
          <td><a href="/news/?&amp;b=k202610010011">新会社、経常利益を上方修正</a></td>
          </tr></table>'''
        raw = stock_news._parse_news_list(html, 'kabutan_stock')
        self.assertEqual((raw[0]['code'], raw[0]['date'], raw[0]['time']),
                         ('646A', '2026-10-01', '15:30'))
        with patch.object(stock_news, '_fetch', return_value=html) as fetch, \
                patch.object(stock_news.time, 'sleep'), \
                patch.object(stock_news, 'NK225_CODES', {'646A'}):
            items = stock_news.fetch_stock_news_pages(max_pages=1)
        self.assertEqual(len(items), 1)
        fetch.assert_called_once_with('https://kabutan.jp/news/?page=1')

    def test_valid_earnings_articles_outside_watchlist_are_a_normal_empty_result(self):
        html = OLD_ARTICLE.replace('<table class="s_news_list">', '<table class="s_news_list">')
        with patch.object(stock_news, '_fetch', return_value=html), \
                patch.object(stock_news.time, 'sleep'), \
                patch.object(stock_news, 'NK225_CODES', {'7203'}):
            self.assertEqual(stock_news.fetch_stock_news_pages(max_pages=1), [])

    def test_unknown_stock_news_page_or_article_format_is_a_failure(self):
        invalid = (
            None,
            '<html>Verify you are human</html>',
            '<table class="s_news_list"><tr><td><a href="/news/changed">決算が上方修正</a></td></tr></table>',
        )
        for html in invalid:
            with self.subTest(html=html), patch.object(stock_news, '_fetch', return_value=html), \
                    self.assertRaises(RuntimeError):
                stock_news.fetch_stock_news_pages(max_pages=1)


if __name__ == '__main__':
    unittest.main()
