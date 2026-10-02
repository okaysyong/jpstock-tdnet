"""Verify a real, recent VPS collector run when GitHub's direct collector fails."""
import argparse
from datetime import datetime, timezone
import os
import re
from urllib.parse import urlsplit
import requests


POLICIES = {'kabutan': (15 * 60, 0), 'push_themes': (8 * 60 * 60, 1)}


def checked_base_url(value):
    if not isinstance(value, str):
        raise ValueError('VPS verification requires an HTTPS base URL')
    value = value.strip().rstrip('/')
    parsed = urlsplit(value)
    if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password
            or parsed.query or parsed.fragment):
        raise ValueError('VPS verification requires an HTTPS base URL')
    return value


def aware_utc(value):
    if not isinstance(value, str):
        raise ValueError('VPS source timestamp is missing')
    try:
        stamp = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if stamp.tzinfo is None or stamp.utcoffset() is None:
            raise ValueError()
        return stamp.astimezone(timezone.utc)
    except (ValueError, OverflowError):
        raise ValueError('VPS source timestamp must include a valid timezone') from None


def validate_source_health(health, name, now=None):
    """A fresh previous success never masks a newer failed or inconsistent attempt."""
    if name not in POLICIES:
        raise ValueError('Unknown VPS source policy')
    if not isinstance(health, dict) or health.get('status') != 'ok':
        raise ValueError('VPS health is not healthy')
    sources = health.get('sources')
    if not isinstance(sources, list):
        raise ValueError('VPS source status list is missing')
    matches = [entry for entry in sources if isinstance(entry, dict) and entry.get('name') == name]
    if len(matches) != 1:
        raise ValueError('VPS source status must be present exactly once')
    source = matches[0]
    if source.get('status') != 'ok':
        raise ValueError('VPS source latest attempt failed')
    success = aware_utc(source.get('last_success'))
    attempt = aware_utc(source.get('last_attempt'))
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None or current.utcoffset() is None:
        raise ValueError('Verification clock must include a timezone')
    current = current.astimezone(timezone.utc)
    age = (current - success).total_seconds()
    if age < -60 or (current - attempt).total_seconds() < -60:
        raise ValueError('VPS source timestamp is in the future')
    if attempt > success:
        raise ValueError('VPS source has an attempt newer than its last success')
    limit, minimum = POLICIES[name]
    if age > limit:
        raise ValueError('VPS source last success is stale')
    count = source.get('count')
    if type(count) is not int or count < minimum:
        raise ValueError('VPS source completed count does not meet its policy')
    return {'name': name, 'last_success': success.isoformat(),
            'age_seconds': round(age, 1), 'reported_count': count}


def validate_theme_codes(payload):
    if not isinstance(payload, dict) or payload.get('ok') is not True:
        raise ValueError('VPS theme collection result is invalid')
    codes = payload.get('codes')
    if not isinstance(codes, list) or not codes:
        raise ValueError('VPS has no recent completed theme codes')
    if any(not isinstance(code, str) or not re.fullmatch(r'(?:[0-9]{4}|[0-9]{3}[A-Z])', code)
           for code in codes):
        raise ValueError('VPS completed theme codes are invalid')
    return len(set(codes))


def get_json(base, path, client=None):
    response = None
    try:
        response = (client or requests).get(base + path, timeout=15, allow_redirects=False)
        if response.status_code != 200:
            raise ValueError()
        content_type = response.headers.get('Content-Type', '').split(';', 1)[0].strip().lower()
        if content_type != 'application/json' and not (content_type.startswith('application/')
                                                       and content_type.endswith('+json')):
            raise ValueError()
        result = response.json()
        if not isinstance(result, dict):
            raise ValueError()
        return result
    except (requests.RequestException, ValueError):
        code = getattr(response, 'status_code', None)
        status = f'HTTP {code}' if type(code) is int and 100 <= code <= 599 else 'HTTP unavailable'
        raise RuntimeError(f'VPS source verification response failed ({status})') from None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', choices=POLICIES, required=True)
    args = parser.parse_args(argv)
    base = checked_base_url(os.getenv('VPS_URL') or os.getenv('VPS_NEWS_API_URL')
                            or os.getenv('VPS_BASE_URL'))
    proof = validate_source_health(get_json(base, '/health'), args.source)
    if args.source == 'push_themes':
        proof['recent_completed_codes'] = validate_theme_codes(
            get_json(base, '/themes/collected?max_age_days=7'))
    detail = (f"source={proof['name']} last_success={proof['last_success']} "
              f"age_seconds={proof['age_seconds']} reported_count={proof['reported_count']}")
    if 'recent_completed_codes' in proof:
        detail += f" recent_completed_codes={proof['recent_completed_codes']}"
    message = 'VPS FALLBACK VERIFIED: GitHub direct collection failed; recent VPS execution verified. ' + detail
    print(message)
    summary = os.getenv('GITHUB_STEP_SUMMARY')
    if summary:
        with open(summary, 'a', encoding='utf-8') as stream:
            stream.write('### VPS fallback execution verified\n\n'
                         'The GitHub direct collector failed. This step verified a recent real VPS '
                         'collector execution; it does not claim successful direct GitHub collection.\n\n'
                         + detail + '\n')
    return proof


if __name__ == '__main__':
    main()
