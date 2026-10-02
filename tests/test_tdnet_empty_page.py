"""Official no-disclosures page vs blocked/unknown HTML; all HTTP is fake."""
from datetime import datetime, timedelta, timezone
import ast
import importlib.util
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
spec = importlib.util.spec_from_file_location('tdnet_empty_page_collector', ROOT/'collect_tdnet.py')
collector = importlib.util.module_from_spec(spec)
spec.loader.exec_module(collector)
JST = timezone(timedelta(hours=9))
NOW = datetime(2026, 10, 3, 2, 41, tzinfo=JST)
EMPTY = (ROOT/'tests/fixtures/tdnet_empty_20261003.html').read_text(encoding='utf-8')


class Response:
    def __init__(self, text, status=200):
        self.text, self.status_code, self.encoding = text, status, 'utf-8'

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError('fake HTTP failure')


class TdnetEmptyPageTests(unittest.TestCase):
    def fetch(self, html, status=200, now=NOW):
        with patch.object(collector.requests, 'get', return_value=Response(html, status)) as get:
            result = collector.fetch_tdnet(now)
            self.assertEqual(get.call_count, 1)
            self.assertIn(now.astimezone(JST).strftime('%Y%m%d'), get.call_args.args[0])
            return result

    def test_official_matching_date_empty_template_is_successful_zero_items(self):
        self.assertEqual(self.fetch(EMPTY), [])
        with patch('collector_common.push_json') as push:
            self.assertEqual(collector.push_to_vps([])['total'], 0)
            push.assert_not_called()

    def test_jst_requested_date_matches_even_when_caller_uses_utc(self):
        self.assertEqual(self.fetch(EMPTY, now=NOW.astimezone(timezone.utc)), [])

    def test_previous_day_page_cannot_claim_today_had_no_disclosures(self):
        with self.assertRaisesRegex(RuntimeError, 'page 1 collection failed'):
            self.fetch(EMPTY.replace('2026年10月03日', '2026年10月02日'))

    def test_missing_or_nonliteral_empty_message_remains_failure(self):
        for text in ('アクセスできません。', '情報を取得できませんでした。', ''):
            with self.subTest(text=text), self.assertRaises(RuntimeError):
                self.fetch(EMPTY.replace('に開示された情報はありません。', text))

    def test_arbitrary_or_blocked_html_is_not_a_healthy_empty_response(self):
        for html in ('<html>Access denied</html>', '<html>2026年10月03日に開示された情報はありません。</html>',
                     EMPTY.replace('適時開示情報閲覧サービス - 開示情報一覧', 'Access denied'),
                     EMPTY.replace('id="main-list"', 'id="unknown-list"'),
                     '<table id="main-list-table"></table>'):
            with self.subTest(html=html[:50]), self.assertRaises(RuntimeError):
                self.fetch(html)

    def test_error_http_and_first_page_404_are_not_confirmed_empty(self):
        for status in (403, 404, 429, 500):
            with self.subTest(status=status), self.assertRaises(RuntimeError):
                self.fetch(EMPTY, status=status)

    def test_empty_notice_cannot_hide_list_content_or_ambiguous_dates(self):
        for html in (EMPTY.replace('style="height:55px;">', 'style="height:55px;">blocked'),
                     EMPTY.replace('style="height:55px;">', 'style="height:55px;"><a href="a.pdf">release</a>'),
                     EMPTY.replace('</body>', '<div id="kaiji-date-1">2026年10月03日</div></body>')):
            with self.subTest(html=html[:50]), self.assertRaises(RuntimeError):
                self.fetch(html)

    def test_later_page_404_terminates_a_successful_nonempty_listing(self):
        rows = ''.join(f'<tr><td class="kjTime">15:00</td><td class="kjCode">72030</td>'
                       f'<td class="kjName">トヨタ</td><td class="kjTitle"><a href="{i}.pdf">発表{i}</a></td></tr>'
                       for i in range(50))
        with patch.object(collector.requests, 'get', side_effect=[
                Response('<table id="main-list-table">'+rows+'</table>'), Response('', 404)]):
            self.assertEqual(len(collector.fetch_tdnet(NOW)), 50)

    def test_vps_copy_uses_identical_parser_when_workspace_copy_exists(self):
        vps = ROOT.parent/'vps-source/backend/jpstock/collect_tdnet.py'
        if not vps.is_file():
            self.skipTest('Standalone GitHub checkout has no VPS workspace copy')
        def functions(path):
            return {node.name: ast.dump(node, include_attributes=False)
                    for node in ast.parse(path.read_text(encoding='utf-8-sig')).body
                    if isinstance(node, ast.FunctionDef)}
        github, server = functions(ROOT/'collect_tdnet.py'), functions(vps)
        for name in ('_confirmed_empty_page', 'fetch_tdnet'):
            self.assertEqual(github[name], server[name])


if __name__ == '__main__':
    unittest.main()
