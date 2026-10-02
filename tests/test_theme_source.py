"""Unknown HTML cannot erase a security's existing investment themes."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import collect_themes as themes


class Page:
    def __init__(self, text, status=200):
        self.text, self.status_code = text, status
    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError('Provider failure')


def stock_page(contents, code='8035'):
    return f'<h1 id="kobetsu">会社({code}) 基本情報</h1><table><tr><th>テーマ</th><td>{contents}</td></tr></table>'


def mobile_page(contents, code='8035'):
    return (f'<title>会社【{code}】の株価・基本情報 - 株探</title>'
            f'<link rel="canonical" href="https://kabutan.jp/stock/?code={code}">'
            '<a href="/themes/wrong/">Wrong sidebar theme</a>'
            '<div data-controller="stocks--basic-info"><div>関連テーマ</div><div>'
            f'<ol data-stocks--basic-info-target="themeContainer">{contents}</ol></div></div>')


class ThemeSource(unittest.TestCase):
    def test_mobile_fallback_from_desktop_405_is_identity_checked(self):
        html = mobile_page('<li><a href="/themes/semiconductor/">半導体</a></li>')
        with patch.object(themes.SESSION, 'get', side_effect=[Page('Unavailable', 405), Page(html)]) as get:
            self.assertEqual(themes.fetch_kabutan_themes('8035'), ['半導体'])
        self.assertEqual([c.args[0] for c in get.call_args_list],
                         ['https://kabutan.jp/stock/?code=8035', 'https://s.kabutan.jp/stocks/8035/'])
        self.assertTrue(all(c.kwargs['timeout'] == (4, 8) and c.kwargs['allow_redirects'] is False
                            for c in get.call_args_list))

    def test_mobile_wrong_code_missing_label_and_sidebar_links_are_rejected(self):
        html = mobile_page('<li><a href="/themes/semiconductor/">半導体</a></li>')
        for wrong in (html.replace('code=8035', 'code=7203'), html.replace('【8035】', '【7203】'),
                      html.replace('関連テーマ', 'ニュース'), html.replace('themeContainer', 'otherSection')):
            with self.subTest(wrong=wrong), self.assertRaises(ValueError):
                themes.parse_kabutan_themes(wrong, '8035')

    def test_mobile_empty_and_alphanumeric_security_are_supported(self):
        self.assertEqual(themes.parse_kabutan_themes(mobile_page('', '186A'), '186A'), [])

    def test_explicit_access_or_rate_limit_rejection_does_not_retry_other_host(self):
        for status in (401, 403, 429):
            with patch.object(themes.SESSION, 'get', return_value=Page('Denied', status)) as get, \
                    self.assertRaises(RuntimeError):
                themes.fetch_kabutan_themes('8035')
            get.assert_called_once()

    def test_partial_failure_keeps_other_verified_items_and_never_pushes_failed_code(self):
        with patch.object(themes, 'get_all_codes_from_vps', return_value=['8035', '7203']), \
                patch.object(themes, 'get_already_done_from_vps', return_value=set()), \
                patch.object(themes, 'fetch_kabutan_themes', side_effect=[RuntimeError('source unavailable'), ['自動車']]), \
                patch.object(themes.time, 'sleep'), patch.object(themes, 'log'), \
                patch.object(themes, 'push_to_vps') as push:
            themes.main()
        push.assert_called_once_with([{'code': '7203', 'themes': ['自動車'], 'source': 'kabutan'}])

    def test_provider_rate_limit_stops_further_requests_but_flushes_verified_batch(self):
        with patch.object(themes, 'get_all_codes_from_vps', return_value=['7203', '8035', '6758']), \
                patch.object(themes, 'get_already_done_from_vps', return_value=set()), \
                patch.object(themes, 'fetch_kabutan_themes', side_effect=[['自動車'], themes.ThemeAccessDenied('rate limit')]) as fetch, \
                patch.object(themes.time, 'sleep'), patch.object(themes, 'log'), \
                patch.object(themes, 'push_to_vps') as push:
            themes.main()
        self.assertEqual(fetch.call_count, 2)
        push.assert_called_once_with([{'code': '7203', 'themes': ['自動車'], 'source': 'kabutan'}])

    def test_only_verified_theme_field_is_used(self):
        html = '<a href="/themes/?theme=outside">Wrong sidebar theme</a>'
        html += stock_page('<a href="/themes/?theme=semi">半導体</a><a href="/themes/?theme=semi">半導体</a>')
        with patch.object(themes.SESSION, 'get', return_value=Page(html)):
            self.assertEqual(themes.fetch_kabutan_themes('8035'), ['半導体'])

    def test_valid_empty_theme_field_is_allowed(self):
        for empty in ('', '-', 'なし', '<a href="/themes/?theme=index">TOPIXコア30</a>'):
            with self.subTest(empty=empty), patch.object(themes.SESSION, 'get', return_value=Page(stock_page(empty))):
                self.assertEqual(themes.fetch_kabutan_themes('8035'), [])

    def test_http_block_unknown_html_wrong_code_and_changed_section_fail(self):
        cases = (
            Page('<html>Denied</html>', 403),
            Page('<html>Verify human</html>'),
            Page(stock_page('<a href="/themes/?theme=semi">半導体</a>', code='7203')),
            Page('<h1 id="kobetsu">会社(8035) 基本情報</h1>'),
            Page(stock_page('Unable to load themes')),
        )
        for page in cases:
            with self.subTest(page=page), patch.object(themes.SESSION, 'get', return_value=page), \
                    self.assertRaises(RuntimeError):
                themes.fetch_kabutan_themes('8035')

    def test_unknown_html_does_not_send_an_empty_update(self):
        with patch.object(themes, 'get_all_codes_from_vps', return_value=['8035']), \
                patch.object(themes, 'get_already_done_from_vps', return_value=set()), \
                patch.object(themes.SESSION, 'get', return_value=Page('<html>Unavailable</html>')), \
                patch.object(themes, 'push_to_vps') as push, self.assertRaises(RuntimeError):
            themes.main()
        push.assert_not_called()


if __name__ == '__main__':
    unittest.main()
