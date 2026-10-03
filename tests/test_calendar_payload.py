"""Original calendar clock/result fixtures; HTTP and VPS delivery are always fake."""
import contextlib
from datetime import datetime, timezone
import importlib.util
import io
from pathlib import Path
import re
import sys
import types
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
spec = importlib.util.spec_from_file_location('calendar_payload_test', ROOT / 'collect_calendar.py')
calendar = importlib.util.module_from_spec(spec)
spec.loader.exec_module(calendar)


def nikkei_row(clock, stars, title, actual, flag='us'):
    return f'''<tr><td class="time">{clock}</td><td class="priority">{stars}</td>
    <td class="event"><span class="flag1-{flag}"></span>{title}</td>
    <td class="result">{actual}</td><td class="expectation">forecast</td><td class="last">previous</td></tr>'''


NIKKEI_FIXTURE = '<table id="SihyoT"><tr><td class="date">10/7</td></tr>' + ''.join([
    # The original source day's 27:00 is the following day's 03:00 JST.
    nikkei_row('27:00', '★★★★', '09月 FOMC議事録', '未発表'),
    nikkei_row('9:00', '★★★★★★★', '日本 GDP', '0', flag='jp'),
    nikkei_row('22:00', '★★★', '米国 指標', '―'),
    nikkei_row('08:99', '★★★★', 'Broken clock must not enter the batch', '1'),
    *[nikkei_row('10:00', '★', f'Low importance {index}', '') for index in range(7)],
]) + '</table>'


FF_FIXTURE = [
    # Same real event after the Nikkei source clock rolls forward: deduplicate it.
    {'title': '09月 FOMC議事録', 'country': 'USD', 'impact': 'High',
     'date': '2026-10-07T18:00:00Z', 'actual': None},
    {'title': 'Unemployment Rate', 'country': 'USD', 'impact': 'High',
     'date': '2026-10-08T18:00:00Z', 'actual': 0, 'previous': 1},
    {'title': 'Not released', 'country': 'JPY', 'impact': 'Medium',
     'date': '2026-10-08T00:00:00Z', 'actual': '-'},
    {'title': 'Ambiguous date must not enter the batch', 'country': 'USD', 'impact': 'High',
     'date': '2026-10-08T03:00:00', 'actual': 4},
]


class FrozenDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        # Reported values in this fixture are valid only after their release.
        now = cls(2026, 10, 9, 3, 0, tzinfo=timezone.utc)
        return now.astimezone(tz) if tz else now.replace(tzinfo=None)


class CalendarPayloadTests(unittest.TestCase):
    def test_extended_source_clock_rolls_date_forward_and_matches_forexfactory(self):
        self.assertEqual(calendar.normalize_schedule_time('2026-10-07', '27:00'),
                         ('2026-10-08', '03:00'))
        self.assertEqual(calendar.forexfactory_time('2026-10-07T18:00:00Z'),
                         ('2026-10-08', '03:00'))
        self.assertEqual(calendar.normalize_schedule_time('2026-12-31', '24:30'),
                         ('2027-01-01', '00:30'))
        self.assertEqual(calendar.normalize_schedule_time('2026-10-07', '9:00'),
                         ('2026-10-07', '09:00'))
        self.assertEqual(calendar.normalize_schedule_time('2026-10-07', '９：００'),
                         ('2026-10-07', '09:00'))

    def test_invalid_schedule_clocks_are_skipped_without_guessed_midnight(self):
        for clock in ('未定', '--:--', '08:99', '48:00', '21:30 later', '', None):
            with self.subTest(clock=clock), self.assertRaises(ValueError):
                calendar.normalize_schedule_time('2026-10-07', clock)

    def test_unreleased_placeholders_do_not_become_actual_results(self):
        for value in (None, '', ' ', '-', '--', '―', '—', '－', '未発表', '未公表',
                      '未定', '発表前', 'N/A', 'pending'):
            with self.subTest(value=value):
                result = calendar.normalize_actual(value)
                self.assertIsNone(result)
                self.assertFalse(calendar.released_actual(result))

    def test_zero_is_a_real_result_and_is_counted_as_released(self):
        for value in (0, 0.0, '0', '0.0', '0%', '-0.1%', '-1'):
            with self.subTest(value=value):
                result = calendar.normalize_actual(value)
                self.assertEqual(result, value)
                self.assertTrue(calendar.released_actual(result))

    def test_importance_is_bounded_to_vps_one_through_five(self):
        self.assertEqual([calendar.normalize_stars(value) for value in (0, 1, 3, 5, 7)],
                         [1, 1, 3, 5, 5])

    def test_full_source_fixture_produces_valid_date_time_and_release_state(self):
        import requests
        page = types.SimpleNamespace(status_code=200, text=NIKKEI_FIXTURE)
        first_ff = types.SimpleNamespace(status_code=200, json=lambda: FF_FIXTURE)
        second_ff = types.SimpleNamespace(status_code=200, json=lambda: [])
        captured = []
        def capture(base, path, payload, **kwargs):
            self.assertEqual(path, '/push/ff_events')
            captured.extend(payload['items'])
            return {'ok': True, 'saved': len(payload['items'])}
        with patch.object(requests, 'get', side_effect=[page, first_ff, second_ff]), \
             patch.object(calendar, 'push_json', side_effect=capture), \
             patch('datetime.datetime', FrozenDateTime), \
             contextlib.redirect_stdout(io.StringIO()) as output:
            calendar.main()
        self.assertEqual(len(captured), 5)
        fomc = [item for item in captured if item['title'] == '09月 FOMC議事録']
        self.assertEqual(len(fomc), 1)
        self.assertEqual((fomc[0]['date'], fomc[0]['time']), ('2026-10-08', '03:00'))
        self.assertEqual(fomc[0]['source'], 'nikkei225jp')
        self.assertIsNone(fomc[0]['actual'])
        gdp = next(item for item in captured if item['title'] == '日本 GDP')
        self.assertEqual((gdp['time'], gdp['stars'], gdp['actual']), ('09:00', 5, '0'))
        unemployment = next(item for item in captured if item['title'] == 'Unemployment Rate')
        self.assertEqual(unemployment['actual'], 0)
        self.assertEqual(unemployment['source'], 'forexfactory')
        self.assertIn('actual: 2건', output.getvalue())
        for item in captured:
            with self.subTest(item=item):
                datetime.strptime(item['date'], '%Y-%m-%d')
                self.assertRegex(item['time'], r'^\d{2}:\d{2}$')
                datetime.strptime(item['time'], '%H:%M')
                self.assertRegex(item['currency'], r'^[A-Z]{3}$')
                if 'stars' in item:
                    self.assertTrue(1 <= item['stars'] <= 5)

    def test_result_refresh_can_skip_schedule_only_ff_downloads(self):
        import requests
        page = types.SimpleNamespace(status_code=200, text=NIKKEI_FIXTURE)
        captured = []
        def capture(base, path, payload, **kwargs):
            captured.extend(payload['items'])
            return {'ok': True, 'saved': len(payload['items'])}
        with patch.object(requests, 'get', return_value=page) as get, \
             patch.object(calendar, 'push_json', side_effect=capture), \
             patch('datetime.datetime', FrozenDateTime), \
             contextlib.redirect_stdout(io.StringIO()):
            calendar.main(include_forexfactory=False)
        self.assertEqual(get.call_count, 1)
        self.assertTrue(all(item['source'] == 'nikkei225jp' for item in captured))
        self.assertTrue(all(item['source_actual_capable'] for item in captured))

    def test_schedule_cadence_unchanged_and_ff_is_hourly(self):
        workflow = (ROOT / '.github/workflows/ff_calendar.yml').read_text(encoding='utf-8')
        self.assertIn("cron: '4 * * * *'", workflow)
        self.assertIn("cron: '19,34,49 * * * *'", workflow)
        self.assertIn('python collect_calendar.py --skip-forexfactory', workflow)
        self.assertIn('CALENDAR_SCHEDULE: ${{ github.event.schedule }}', workflow)


if __name__ == '__main__':
    unittest.main()
