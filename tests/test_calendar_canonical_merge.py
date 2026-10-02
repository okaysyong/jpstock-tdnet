"""Economic release merge fixtures; no actual source requests or server writes."""
from datetime import datetime
import importlib.util
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
spec = importlib.util.spec_from_file_location('calendar_canonical_merge_test', ROOT / 'collect_calendar.py')
calendar = importlib.util.module_from_spec(spec)
spec.loader.exec_module(calendar)


def nikkei(title, actual=None, clock='21:30', currency='USD'):
    return {'date': '2026-10-02', 'time': clock, 'currency': currency, 'title': title,
            'actual': actual, 'stars': 5, 'forecast': '9.5万人', 'previous': '16.2万人'}


def ff(title, **changes):
    return {'country': 'USD', 'title': title, 'date': '2026-10-02T08:30:00-04:00',
            'impact': 'High', 'forecast': '89K', 'previous': '162K', **changes}


class CalendarCanonicalMergeTests(unittest.TestCase):
    NOW = datetime.fromisoformat('2026-10-02T22:00:00+09:00')

    def build(self, nk=(), factory=(), now=None):
        return calendar.build_payload(nk, factory, now or self.NOW)

    def test_japanese_wrapped_monthly_employment_matches_english(self):
        items = self.build([nikkei('09月 雇用統計（非農業部門雇用者数）[前月比]', '2.9万人'),
                            nikkei('09月 雇用統計（失業率）', '4.2%')],
                           [ff('Non-Farm Employment Change'), ff('Unemployment Rate')])
        self.assertEqual(len(items), 2)
        self.assertEqual({item['actual'] for item in items}, {'2.9万人', '4.2%'})
        self.assertTrue(all(item['source'] == 'nikkei225jp' for item in items))
        self.assertTrue(all(item['result_status'] == 'reported' for item in items))

    def test_weekly_mirrors_and_duplicate_source_rows_deduplicate(self):
        source = ff('Unemployment Rate')
        items = self.build([], [source, dict(source), dict(source)])
        self.assertEqual(len(items), 1)
        self.assertIsNone(items[0]['actual'])
        self.assertEqual(items[0]['result_status'], 'schedule_only')
        self.assertFalse(items[0]['source_actual_capable'])

    def test_monthly_and_yearly_earnings_do_not_merge(self):
        items = self.build([nikkei('09月 雇用統計（平均時給）[前月比]', '0.1%'),
                            nikkei('09月 雇用統計（平均時給）[前年比]', '3.0%')],
                           [ff('Average Hourly Earnings m/m')])
        self.assertEqual(len(items), 2)
        self.assertEqual({item['actual'] for item in items}, {'0.1%', '3.0%'})

    def test_different_explicit_reference_periods_remain_separate(self):
        items = self.build([nikkei('08月 雇用統計（失業率）', '4.1%')], [ff('Unemployment Rate')])
        self.assertEqual(len(items), 2)

    def test_different_country_same_title_and_clock_remain_separate(self):
        items = self.build([], [ff('Unemployment Rate'), ff('Unemployment Rate', country='JPY')])
        self.assertEqual(len(items), 2)

    def test_zero_result_beats_unreleased_copy(self):
        items = self.build([nikkei('09月 雇用統計（非農業部門雇用者数）[前月比]', None),
                            nikkei('09月 雇用統計（非農業部門雇用者数）[前月比]', 0)],
                           [ff('Non-Farm Employment Change')])
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]['actual'], 0)
        self.assertEqual(items[0]['result_status'], 'reported')

    def test_explicit_ff_zero_result_if_feed_contract_supplies_actual(self):
        item = self.build([], [ff('Unemployment Rate', actual=0)])[0]
        self.assertEqual(item['actual'], 0)
        self.assertTrue(item['source_actual_capable'])
        self.assertEqual(item['result_status'], 'reported')

    def test_future_actual_cannot_be_announced_before_release(self):
        items = self.build([nikkei('09月 雇用統計（失業率）', '4.2%')], [],
                           datetime.fromisoformat('2026-10-02T21:29:59+09:00'))
        self.assertIsNone(items[0]['actual'])
        self.assertEqual(items[0]['result_status'], 'awaiting')

    def test_actual_allowed_at_exact_scheduled_time(self):
        item = self.build([nikkei('09月 雇用統計（失業率）', '4.2%')], [],
                          datetime.fromisoformat('2026-10-02T21:30:00+09:00'))[0]
        self.assertEqual(item['actual'], '4.2%')

    def test_forecast_and_previous_not_mixed_across_providers(self):
        item = self.build([nikkei('09月 雇用統計（非農業部門雇用者数）[前月比]', '2.9万人')],
                          [ff('Non-Farm Employment Change')])[0]
        self.assertEqual(item['forecast'], '9.5万人')
        self.assertEqual(item['previous'], '16.2万人')

    def test_observed_timestamp_and_stable_identity_are_present(self):
        item = self.build([nikkei('09月 雇用統計（失業率）', '4.2%')])[0]
        self.assertEqual(item['observed_at'], '2026-10-02T13:00:00+00:00')
        self.assertTrue(item['canonical_id'])
        self.assertTrue(item['scheduled_at'])

    def test_boolean_or_nonfinite_actual_is_not_a_release(self):
        for bad in (True, False, float('nan'), float('inf')):
            with self.subTest(value=bad):
                self.assertIsNone(calendar.normalize_actual(bad))

    def test_unfamiliar_indicator_titles_do_not_fuzzy_merge(self):
        items = self.build([], [ff('Private Payrolls'), ff('Non-Farm Employment Change')])
        self.assertEqual(len(items), 2)

    def test_tokyo_core_cpi_missing_period_uses_unique_explicit_peer(self):
        jp = nikkei('09月 東京消費者物価指数（CPIコア指数）[前年比]', '2.7%', clock='08:30', currency='JPY')
        en = ff('Tokyo Core CPI y/y', country='JPY', date='2026-10-01T23:30:00Z')
        items = self.build([jp], [en])
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]['actual'], '2.7%')
        self.assertEqual(items[0]['period'], '2026-09')

    def test_ambiguous_reference_period_never_bridges_two_releases(self):
        jp = nikkei('09月 東京消費者物価指数（CPIコア指数）[前年比]', '2.7%', clock='08:30', currency='JPY')
        previous = dict(jp, title=jp['title'].replace('09月', '08月'))
        en = ff('Tokyo Core CPI y/y', country='JPY', date='2026-10-01T23:30:00Z')
        self.assertEqual(len(self.build([jp, previous], [en])), 3)


if __name__ == '__main__':
    unittest.main()
