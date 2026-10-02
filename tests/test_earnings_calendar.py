"""Selected earnings table fixtures; no navigation or previous-quarter borrowing."""
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch
import requests


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
spec = importlib.util.spec_from_file_location('earnings_calendar_test', ROOT / 'fetch_kessan.py')
earnings = importlib.util.module_from_spec(spec)
spec.loader.exec_module(earnings)


HEADERS = '<tr><th>銘柄名 (コード)</th><th colspan="3">決算発表(予定)</th></tr>'


def row(code='3035', name='ＫＴＫ', announced='2026/10/02', period='本', prior_period='3Q'):
    return f'''<tr><td><a href="/reportTop?bcode={code}">
    <p>{name}</p><span class="nmbr">{code}</span></a></td>
    <td><span>{announced}</span></td><td>2026/08</td><td><span>{period}</span></td>
    <td>600</td><td>488 <i>({prior_period})</i></td><td>81.3</td></tr>'''


class EarningsCalendarTests(unittest.TestCase):
    def test_actual_container_without_stocklist_id_ignores_navigation_and_other_dates(self):
        html = f'''<a href="/reportTop?bcode=9999" title="Navigation">nav</a>
        <section class="cldr cldr_today"><h2>2026/10/02 の決算発表予定</h2>
        <div class="result"><table>{HEADERS}{row()}
          {row('7870', '福島印刷', '2026/10/01')}</table></div></section>
        <section><table>{HEADERS}{row('7203', 'Another day')}</table></section>'''
        items = earnings.parse_kabuyoho_html(html, '2026-10-02')
        self.assertEqual([item['code'] for item in items], ['3035'])
        self.assertEqual(items[0]['name'], 'ＫＴＫ')
        self.assertEqual(items[0]['kessan_date'], '2026-10-02')
        self.assertEqual(items[0]['fiscal_period'], '本決算')

    def test_id_spacing_attribute_order_and_alphanumeric_codes_are_supported(self):
        html = f'''<section data-kind="calendar" id = 'stocklist' class="result">
          <table>{HEADERS}{row('285A', '日本の新会社', period='２Ｑ')}
          {row('285A', 'Duplicate', period='2Q')}
          {row('285AB', 'Invalid five-character code', period='2Q')}</table></section>'''
        items = earnings.parse_kabuyoho_html(html, '2026-10-02')
        self.assertEqual([item['code'] for item in items], ['285A'])
        self.assertEqual(items[0]['fiscal_period'], '2Q')

    def test_valid_empty_table_without_any_source_date_is_a_real_empty_result(self):
        html = f'''<section class="cldr_today"><div class="result">
          <table>{HEADERS}<tr><td colspan="8">該当する銘柄はありません</td></tr></table>
          </div></section>'''
        self.assertEqual(earnings.parse_kabuyoho_html(html, '2026-10-02'), [])

    def test_missing_target_or_earnings_table_is_a_format_failure(self):
        for html in ('<html>Unavailable</html>', '<a href="#stocklist">calendar</a>',
                     '<section id="stocklist"><table><tr><td>random page</td></tr></table></section>'):
            with self.subTest(html=html), self.assertRaisesRegex(RuntimeError, 'page format changed'):
                earnings.parse_kabuyoho_html(html, '2026-10-02')

    def test_real_stock_row_without_source_date_fails_instead_of_inventing_requested_date(self):
        html = f'<section id="stocklist"><table>{HEADERS}{row(announced="")}</table></section>'
        with self.assertRaisesRegex(RuntimeError, 'row format changed'):
            earnings.parse_kabuyoho_html(html, '2026-10-02')

    def test_name_is_limited_to_twenty_without_dropping_long_company(self):
        name = '日本の長い会社名称を省略せずにまず読むための名前'
        html = f'<section id="stocklist"><table>{HEADERS}{row(name=name)}</table></section>'
        item = earnings.parse_kabuyoho_html(html, '2026-10-02')[0]
        self.assertEqual(item['name'], name[:20])
        self.assertEqual(item['market'], '')
        self.assertEqual(item['kessan_time'], '')
        self.assertEqual(item['source'], 'kabuyoho')

    def test_scheduled_period_does_not_borrow_prior_profit_quarter(self):
        html = f'<section id="stocklist"><table>{HEADERS}{row(period="", prior_period="3Q")}</table></section>'
        self.assertEqual(earnings.parse_kabuyoho_html(html, '2026-10-02')[0]['fiscal_period'], '')

    def test_get_contract_and_download_failure_are_preserved(self):
        response = types.SimpleNamespace(text=f'<section id="stocklist"><table>{HEADERS}{row()}</table></section>',
                                         raise_for_status=lambda: None)
        with patch.object(earnings.requests, 'get', return_value=response) as get:
            self.assertEqual(len(earnings.fetch_kabuyoho_date('2026-10-02')), 1)
        self.assertIn('lst=20261002', get.call_args.args[0])
        self.assertIn('sett=4', get.call_args.args[0])
        self.assertEqual(get.call_args.kwargs['timeout'], 15)
        with patch.object(earnings.requests, 'get', side_effect=requests.ConnectionError('private detail')):
            with self.assertRaisesRegex(RuntimeError, '^Earnings calendar download failed$'):
                earnings.fetch_kabuyoho_date('2026-10-02')


if __name__ == '__main__':
    unittest.main()
