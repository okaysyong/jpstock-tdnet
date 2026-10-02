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


class ThemeSource(unittest.TestCase):
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
