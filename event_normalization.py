"""Conservative economic-calendar identity and parsing, with no I/O on import."""
from datetime import date as Date, datetime, timedelta, timezone
import hashlib
import math
import re
import unicodedata

JST = timezone(timedelta(hours=9))
COUNTRIES = {'USD':'US','JPY':'JP','EUR':'EU','GBP':'GB','AUD':'AU','CNY':'CN',
             'CAD':'CA','CHF':'CH','NZD':'NZ','UK':'GB'}
EMPTY_VALUES = {'', '-', '--', '—', '–', '−', '―', 'ー', 'n/a', 'na', 'none', 'null', 'nan',
                '未発表', '未公表', '未定', '発表待ち', '発表前', 'pending', 'tba',
                'not released', 'not yet released'}


def normalized_value(value):
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) and not math.isfinite(value):
        return None
    text = unicodedata.normalize('NFKC', str(value)).strip()
    return None if text.casefold() in EMPTY_VALUES or (text and all(c in '-—–−―ー ' for c in text)) else text


def normalize_country(value):
    value = str(value or '').upper().strip()
    return COUNTRIES.get(value, value)


def _text(value):
    return unicodedata.normalize('NFKC', str(value or '')).casefold().strip()


def canonical_fields(date, time, country, title, period=None):
    day = Date.fromisoformat(str(date))
    clock = str(time or '').strip()[:5]
    country = normalize_country(country)
    text = _text(title)
    explicit = re.match(r'^(?:(\d{4})年\s*)?(\d{1,2})月\s*', text)
    if explicit:
        month = int(explicit[2])
        if 1 <= month <= 12:
            year = int(explicit[1]) if explicit[1] else day.year - int(month > day.month)
            period = period or f'{year:04d}-{month:02d}'
            text = text[explicit.end():]
    basis = ''
    for label, pattern in (('yoy', r'前年比|前年同月比|y\s*/\s*y|yoy|year.over.year'),
                           ('mom', r'前月比|m\s*/\s*m|mom|month.over.month'),
                           ('qoq', r'前期比|q\s*/\s*q|qoq|quarter.over.quarter')):
        if re.search(pattern, text):
            basis = label
            text = re.sub(pattern, '', text)
            break
    compact = ''.join(c for c in text if c.isalnum())
    while compact.startswith('雇用統計雇用統計'):
        compact = compact[len('雇用統計'):]
    aliases = {
        'nonfarmemploymentchange':'nonfarm_payrolls', 'nonfarmpayrolls':'nonfarm_payrolls',
        '非農業部門雇用者数':'nonfarm_payrolls', '雇用統計非農業部門雇用者数':'nonfarm_payrolls',
        '失業率':'unemployment_rate', '雇用統計失業率':'unemployment_rate',
        '完全雇用統計失業率':'unemployment_rate',
        'unemploymentrate':'unemployment_rate',
        '平均時給':'average_hourly_earnings', '雇用統計平均時給':'average_hourly_earnings',
        'averagehourlyearnings':'average_hourly_earnings',
        '新規失業保険申請件数':'initial_jobless_claims',
        'unemploymentclaims':'initial_jobless_claims', 'initialjoblessclaims':'initial_jobless_claims',
        'tokyocorecpi':'tokyo_core_cpi',
        '東京消費者物価指数cpiコア指数':'tokyo_core_cpi',
    }
    indicator = aliases.get(compact, compact)
    # These US labour-series names have known monthly reporting semantics.
    # Unknown indicators retain their full normalized wording and qualifiers.
    monthly = country == 'US' and indicator in {
        'nonfarm_payrolls', 'unemployment_rate', 'average_hourly_earnings'}
    if monthly and not period:
        prior = day.replace(day=1) - timedelta(days=1)
        period = f'{prior:%Y-%m}'
    if country == 'US' and indicator == 'nonfarm_payrolls' and basis in ('', 'mom'):
        basis = 'mom'
    period = str(period or '')
    raw = '|'.join((str(day), clock, country, indicator, period, basis))
    key = hashlib.sha256(raw.encode('utf-8')).hexdigest()[:32]
    scheduled = None
    try:
        scheduled = datetime.fromisoformat(f'{day}T{clock}:00').replace(tzinfo=JST).isoformat()
    except ValueError:
        pass
    return {'canonical_id':key, 'indicator':indicator, 'period':period, 'basis':basis,
            'scheduled_at':scheduled}


def canonical_key(date, time, country, title, period=None):
    return canonical_fields(date, time, country, title, period)['canonical_id']


def canonical_record_fields(event, peers=()):
    """Resolve an omitted period only when an exact series has one unique peer."""
    day = event.get('event_date') or event.get('date')
    clock = event.get('event_time') or event.get('time')
    country = normalize_country(event.get('country') or event.get('currency'))
    title = event.get('title') or event.get('title_jp')
    fields = canonical_fields(day, clock, country, title, event.get('period'))
    known = {'nonfarm_payrolls','unemployment_rate','average_hourly_earnings',
             'initial_jobless_claims','tokyo_core_cpi'}
    if fields['period'] or fields['indicator'] not in known:
        return fields
    periods = set()
    for peer in peers:
        if ((peer.get('event_date') or peer.get('date')) != day or
                (peer.get('event_time') or peer.get('time')) != clock or
                normalize_country(peer.get('country') or peer.get('currency')) != country):
            continue
        other = canonical_fields(day, clock, country, peer.get('title') or peer.get('title_jp'), peer.get('period'))
        if (other['indicator'],other['basis']) == (fields['indicator'],fields['basis']) and other['period']:
            periods.add(other['period'])
    return canonical_fields(day, clock, country, title, periods.pop()) if len(periods) == 1 else fields


def observed_iso(value, fallback=None):
    """Collector timestamps must have an explicit offset; legacy times stay unknown."""
    try:
        stamp = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        if stamp.tzinfo is None:
            return fallback
        return stamp.astimezone(timezone.utc).isoformat()
    except (TypeError, ValueError):
        return fallback


def merge_events(rows):
    rows = [dict(row) for row in rows]
    grouped = {}
    for original in rows:
        event = dict(original)
        fields = canonical_record_fields(event, rows)
        event.update(fields)
        actual = normalized_value(event.get('actual'))
        event['actual'] = (event['actual'] if actual is not None and isinstance(event.get('actual'), (int,float)) else actual)
        event['forecast'] = normalized_value(event.get('forecast'))
        event['previous'] = normalized_value(event.get('previous'))
        event['aliases'] = [str(event['id'])] if event.get('id') else []
        event['id'] = fields['canonical_id']
        event['result_status'] = 'reported' if event['actual'] is not None else (
            'schedule_only' if event.get('source_actual_capable') == 0 else 'awaiting')
        grouped.setdefault(event['id'], []).append(event)
    result = []
    for copies in grouped.values():
        # Timestamp only ranks actual observations, not a later schedule refresh.
        copies.sort(key=lambda e: (e['actual'] is not None,
            observed_iso(e.get('result_updated_at'), '') or '', e.get('source') == 'nikkei225jp'), reverse=True)
        winner = dict(copies[0])
        winner['aliases'] = sorted({alias for e in copies for alias in e['aliases']})
        winner['stars'] = max(int(e.get('stars') or 0) for e in copies)
        for field in ('forecast', 'previous'):
            if winner.get(field) is None:
                winner[field] = next((e[field] for e in copies if e[field] is not None and
                    (winner['actual'] is None or e.get('source') == winner.get('actual_source', winner.get('source')))), None)
        japanese = next((e for e in copies if e.get('source') == 'nikkei225jp'), None)
        if japanese:
            winner['title_jp'] = japanese.get('title_jp') or japanese.get('title')
        winner['is_released'] = int(winner['actual'] is not None)
        result.append(winner)
    return sorted(result, key=lambda e: (e['event_date'], e.get('event_time') or '', -e['stars'], e['id']))


def parse_nikkei_schedule(html, now=None):
    """Parse result/expectation/last cells once for both periodic and fast collectors."""
    from bs4 import BeautifulSoup
    now = now or datetime.now(JST)
    now = now.replace(tzinfo=JST) if now.tzinfo is None else now.astimezone(JST)
    table = BeautifulSoup(html, 'html.parser').find('table', id='SihyoT')
    if table is None:
        raise ValueError('Nikkei calendar table missing')
    day = None
    events = []
    for row in table.find_all('tr'):
        date_cell = row.find('td', class_='date')
        if date_cell:
            match = re.search(r'(\d{1,2})/(\d{1,2})', date_cell.get_text())
            if match:
                candidates = []
                for year in (now.year-1, now.year, now.year+1):
                    try: candidates.append(Date(year, int(match[1]), int(match[2])))
                    except ValueError: pass
                day = min(candidates, key=lambda d: abs((d-now.date()).days)) if candidates else None
        event_cell = row.find('td', class_='event')
        if not day or not event_cell:
            continue
        title = event_cell.get_text(' ', strip=True)
        if any(word in title for word in ('FIFA','ワールドカップ','休日','休場','上場予定')):
            continue
        clock_cell = row.find('td', class_='time')
        match = re.fullmatch(r'(\d{1,2}):(\d{2})', _text(clock_cell.get_text(strip=True) if clock_cell else ''))
        if not match or int(match[1]) > 47 or int(match[2]) > 59:
            continue
        event_day = day + timedelta(days=int(match[1])//24)
        clock = f'{int(match[1])%24:02d}:{int(match[2]):02d}'
        country = None
        for flag in event_cell.find_all(class_=True):
            for css in flag.get('class', []):
                if css.startswith('flag1-'):
                    country = normalize_country(css[6:])
                    break
        if not country:
            continue  # Never assume Japan when the source flag is unrecognized.
        priority = row.find('td', class_='priority')
        stars = priority.get_text().count('★') if priority else 0
        if not 1 <= stars <= 5:
            continue
        def cell_value(*names):
            cell = next((row.find('td', class_=name) for name in names if row.find('td', class_=name)), None)
            return normalized_value(cell.get_text(strip=True)) if cell else None
        actual = cell_value('result')
        events.append({'date':str(event_day), 'time':clock, 'country':country,
            'title':title, 'title_jp':title, 'source':'nikkei225jp', 'stars':stars,
            'actual':actual, 'forecast':cell_value('expectation','forecast'),
            'previous':cell_value('last','previous'), 'source_actual_capable':True,
            'result_status':'reported' if actual is not None else 'awaiting',
            'observed_at':now.astimezone(timezone.utc).isoformat()})
    return events
