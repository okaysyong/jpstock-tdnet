"""Fallback success requires proof of a real, recent VPS collector run."""
import contextlib
from datetime import datetime, timedelta, timezone
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import requests


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import verify_vps_source as verifier


NOW = datetime(2026, 10, 2, 4, 0, tzinfo=timezone.utc)


def health(name='kabutan', age=300, count=0, status='ok', **changes):
    stamp = (NOW - timedelta(seconds=age)).astimezone(timezone(timedelta(hours=9))).isoformat()
    source = dict(name=name, status=status, last_success=stamp, last_attempt=stamp, count=count)
    source.update(changes)
    return {'status': 'ok', 'sources': [source]}


class Reply:
    def __init__(self, payload, status=200, content_type='application/json'):
        self.payload = payload
        self.status_code = status
        self.headers = {'Content-Type': content_type}
    def json(self):
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


class VpsSourceVerificationTests(unittest.TestCase):
    def test_recent_successful_zero_news_run_is_allowed(self):
        proof = verifier.validate_source_health(health(count=0, age=900), 'kabutan', NOW)
        self.assertEqual(proof['reported_count'], 0)
        self.assertEqual(proof['age_seconds'], 900)
        self.assertEqual(proof['last_success'], '2026-10-02T03:45:00+00:00')

    def test_theme_batch_needs_positive_count_and_eight_hour_freshness(self):
        proof = verifier.validate_source_health(health('push_themes', age=28800, count=3), 'push_themes', NOW)
        self.assertEqual(proof['reported_count'], 3)
        for age, count in ((28801, 3), (60, 0)):
            with self.subTest(age=age, count=count), self.assertRaises(ValueError):
                verifier.validate_source_health(health('push_themes', age=age, count=count), 'push_themes', NOW)

    def test_stale_failed_missing_duplicate_and_invalid_count_sources_fail(self):
        bad = [health(age=901), health(status='error'), {'status': 'error', 'sources': []},
               {'status': 'ok'}, {'status': 'ok', 'sources': []},
               health(name='another_source'), health(count=-1), health(count=True), health(count='1')]
        duplicate = health()
        duplicate['sources'] *= 2
        bad.append(duplicate)
        for payload in bad:
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                verifier.validate_source_health(payload, 'kabutan', NOW)

    def test_previous_success_never_masks_a_newer_failed_or_inconsistent_attempt(self):
        newer = (NOW - timedelta(seconds=10)).isoformat()
        for status in ('error', 'ok'):
            with self.subTest(status=status), self.assertRaises(ValueError):
                verifier.validate_source_health(health(age=300, status=status, last_attempt=newer), 'kabutan', NOW)

    def test_naive_missing_broken_and_excessively_future_timestamps_fail(self):
        for stamp in (None, '', '2026-10-02T04:00:00', 'broken',
                      (NOW + timedelta(seconds=61)).isoformat()):
            for field in ('last_success', 'last_attempt'):
                with self.subTest(field=field, stamp=stamp), self.assertRaises(ValueError):
                    verifier.validate_source_health(health(**{field: stamp}), 'kabutan', NOW)
        self.assertEqual(verifier.validate_source_health(health(age=-60), 'kabutan', NOW)['age_seconds'], -60)

    def test_recent_theme_codes_are_required_and_must_be_security_codes(self):
        self.assertEqual(verifier.validate_theme_codes({'ok': True, 'codes': ['7203', '285A', '7203']}), 2)
        for payload in ({'ok': False, 'codes': ['7203']}, {'ok': True, 'codes': []},
                        {'ok': True}, {'ok': True, 'codes': ['285AB']},
                        {'ok': True, 'codes': [7203]}, {'ok': True, 'codes': '7203'}):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                verifier.validate_theme_codes(payload)

    def test_base_url_requires_https_without_credentials_query_or_fragment(self):
        self.assertEqual(verifier.checked_base_url('https://example.test/'), 'https://example.test')
        for value in (None, '', 'http://example.test', 'https://user:secret@example.test',
                      'https://example.test/?token=secret', 'https://example.test/#secret'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                verifier.checked_base_url(value)

    def test_get_does_not_redirect_and_requires_json_http_200(self):
        for response in (Reply({}, 302), Reply({}, 401), Reply({}, 503),
                         Reply({}, content_type='text/html'), Reply([], 200),
                         Reply(ValueError('body-MUST-NOT-APPEAR'))):
            with self.subTest(response=response), patch.object(verifier.requests, 'get', return_value=response) as get:
                with self.assertRaises(RuntimeError) as caught:
                    verifier.get_json('https://example.test', '/health')
                self.assertNotIn('body-MUST-NOT-APPEAR', str(caught.exception))
                self.assertFalse(get.call_args.kwargs['allow_redirects'])
                self.assertEqual(get.call_args.kwargs['timeout'], 15)
        with patch.object(verifier.requests, 'get', side_effect=requests.ConnectionError('URL-token-MUST-NOT-APPEAR')):
            with self.assertRaisesRegex(RuntimeError, r'HTTP unavailable') as caught:
                verifier.get_json('https://example.test', '/health')
            self.assertNotIn('URL-token-MUST-NOT-APPEAR', str(caught.exception))

    def test_main_checks_real_health_and_codes_and_identifies_vps_execution_in_summary(self):
        current = datetime.now(timezone.utc)
        payload = health('push_themes', age=30, count=3)
        stamp = (current - timedelta(seconds=30)).isoformat()
        payload['sources'][0].update(last_success=stamp, last_attempt=stamp)
        with tempfile.TemporaryDirectory() as tmp:
            summary = Path(tmp) / 'summary.md'
            with patch.dict(verifier.os.environ, {'VPS_URL': 'https://example.test', 'GITHUB_STEP_SUMMARY': str(summary)}, clear=True), \
                 patch.object(verifier.requests, 'get', side_effect=[Reply(payload), Reply({'ok': True, 'codes': ['7203']})]) as get, \
                 patch.object(verifier.requests, 'post', side_effect=AssertionError('No POST permitted')), \
                 contextlib.redirect_stdout(io.StringIO()) as output:
                proof = verifier.main(['--source', 'push_themes'])
            self.assertEqual(proof['reported_count'], 3)
            self.assertEqual(proof['recent_completed_codes'], 1)
            self.assertEqual([call.args[0] for call in get.call_args_list],
                ['https://example.test/health', 'https://example.test/themes/collected?max_age_days=7'])
            self.assertIn('GitHub direct collection failed', output.getvalue())
            self.assertIn('VPS FALLBACK VERIFIED', output.getvalue())
            self.assertIn('does not claim successful direct GitHub collection', summary.read_text(encoding='utf-8'))

    def test_workflows_require_vps_verification_after_direct_failure(self):
        for name, source in [('fetch_kabutan.yml', 'kabutan'), ('stock_news.yml', 'kabutan'),
                             ('Collect themes.yml', 'push_themes')]:
            content = (ROOT / '.github/workflows' / name).read_text(encoding='utf-8')
            with self.subTest(workflow=name):
                self.assertIn('id: direct', content)
                self.assertIn('continue-on-error: true', content)
                self.assertIn("if: steps.direct.outcome == 'failure'", content)
                self.assertIn(f'run: python verify_vps_source.py --source {source}', content)
        tests = (ROOT / '.github/workflows/tests.yml').read_text(encoding='utf-8')
        for step in ('kabutan_direct', 'stock_news_direct', 'theme_direct'):
            self.assertIn(f'id: {step}', tests)
            self.assertIn(f"steps.{step}.outcome == 'failure'", tests)
        application = tests.split('  application-check:', 1)[1].split('  market-news-check:', 1)[0]
        self.assertNotIn('continue-on-error', application)
        self.assertNotIn('verify_vps_source', application)


if __name__ == '__main__':
    unittest.main()
