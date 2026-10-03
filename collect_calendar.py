"""Economic calendar collector; import is side-effect free."""
from collector_common import push_json, event_identity
from event_normalization import canonical_record_fields, parse_nikkei_schedule, COMPARISON_FIELDS
from datetime import datetime, timedelta, timezone
import math
import re
import unicodedata


JST = timezone(timedelta(hours=9))


def normalize_schedule_time(source_date, source_time):
    """Nikkei's 27:00 on a source date means 03:00 on the next JST date."""
    clock = unicodedata.normalize('NFKC', str(source_time)).strip()
    match = re.fullmatch(r'(\d{1,2}):(\d{2})', clock)
    if match is None:
        raise ValueError('Invalid economic event clock')
    hour, minute = map(int, match.groups())
    if hour > 47 or minute > 59:
        raise ValueError('Invalid economic event clock')
    day = datetime.strptime(source_date, '%Y-%m-%d')
    event = day + timedelta(hours=hour, minutes=minute)
    return event.strftime('%Y-%m-%d'), event.strftime('%H:%M')


def normalize_actual(value):
    """Keep reported zero; placeholders are not released economic results."""
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value if math.isfinite(value) else None
    text = unicodedata.normalize('NFKC', str(value)).strip()
    if not text or re.fullmatch(r'[-‐‑‒–—―ー−]+', text):
        return None
    if text.casefold() in {'未発表', '未公表', '未定', '発表前', 'n/a', 'na', 'null', 'none',
                           'tba', 'pending', 'not released', 'not yet released'}:
        return None
    return text


def normalize_stars(value):
    # The VPS accepts importance from 1 through 5. Repeated star markup cannot exceed it.
    return min(5, max(1, int(value)))


def released_actual(value):
    return value is not None and (not isinstance(value, str) or bool(value.strip()))


def forexfactory_time(value):
    if not isinstance(value, str):
        raise ValueError('Invalid economic event timestamp')
    event = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if event.tzinfo is None or event.utcoffset() is None:
        raise ValueError('Economic event timestamp has no timezone')
    event = event.astimezone(JST)
    return event.strftime('%Y-%m-%d'), event.strftime('%H:%M')


def build_payload(nikkei_events, ff_items, now=None):
    """One source-consistent record per canonical release, with explicit freshness.

    The weekly FF export normally supplies schedule/forecast/previous only. Missing
    actual is not zero, and repeated weekly copies cannot create duplicate cards.
    """
    now = now or datetime.now(JST)
    now = now.replace(tzinfo=JST) if now.tzinfo is None else now.astimezone(JST)
    observed_at = now.astimezone(timezone.utc).isoformat(timespec='seconds')
    candidates = []
    for event in nikkei_events:
        candidate = {
            'title': event['title'], 'currency': event['currency'], 'source': 'nikkei225jp',
            'impact': 'High' if event['stars'] >= 4 else 'Medium', 'stars': event['stars'],
            'date': event['date'], 'time': event['time'], 'forecast': event.get('forecast'),
            'previous': event.get('previous'), 'actual': normalize_actual(event.get('actual')),
            'source_actual_capable': True,
        }
        candidate.update({k: event[k] for k in COMPARISON_FIELDS if k in event})
        candidates.append(candidate)
    for event in ff_items:
        if not isinstance(event, dict) or event.get('country') not in ('USD', 'JPY'):
            continue
        if event.get('impact') not in ('High', 'Medium'):
            continue
        try:
            day, clock = forexfactory_time(event.get('date', ''))
        except (ValueError, OverflowError):
            continue
        candidates.append({
            'title': event.get('title', ''), 'currency': event['country'], 'source': 'forexfactory',
            'impact': event['impact'], 'date': day, 'time': clock,
            'forecast': event.get('forecast'), 'previous': event.get('previous'),
            'actual': normalize_actual(event.get('actual')),
            'source_actual_capable': 'actual' in event,
        })
    selected = {}
    for item in candidates:
        if not str(item['title']).strip():
            continue
        try:
            due = datetime.fromisoformat(item['date'] + 'T' + item['time']).replace(tzinfo=JST)
            fields = canonical_record_fields(item, candidates)
        except (ValueError, TypeError):
            continue
        # A scraped old result accidentally paired with a future release cannot
        # become a result announcement. The original source can update after due.
        if due > now:
            item['actual'] = None
        item.update(fields)
        item['observed_at'] = observed_at
        item['result_status'] = ('schedule_only' if not item['source_actual_capable'] else
                                 'reported' if released_actual(item['actual']) else 'awaiting')
        key = fields['canonical_id']
        old = selected.get(key)
        priority = (released_actual(item['actual']), item['source'] == 'nikkei225jp')
        old_priority = (released_actual(old['actual']), old['source'] == 'nikkei225jp') if old else None
        # Do not mix conflicting forecasts/previous values from different providers.
        if old is None or priority > old_priority:
            selected[key] = item
    return sorted(selected.values(), key=lambda item: (item['date'], item['time'], item['canonical_id']))


def main(include_forexfactory=True):
    import requests, json, re, os
    from datetime import datetime, timezone, timedelta
    from bs4 import BeautifulSoup
    
    VPS_URL = os.environ.get("VPS_NEWS_API_URL", "").rstrip("/")
    
    JST = timezone(timedelta(hours=9))
    now = datetime.now(JST)
    year = now.year
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "ja,en-US;q=0.9",
    }
    
    # ── nikkei225jp 스크래핑 (flag 클래스로 정확한 국가 판단) ──
    nk_events = []
    successful_sources = 0
    try:
        r = requests.get("https://nikkei225jp.com/schedule/", headers=headers, timeout=15)
        print(f"nikkei225jp: {r.status_code}")
        if r.status_code == 200:
            parsed = parse_nikkei_schedule(r.text, now)
            successful_sources += 1
            currencies = {'JP': 'JPY', 'US': 'USD', 'EU': 'EUR'}
            nk_events = [dict(event, currency=currencies[event['country']])
                         for event in parsed
                         if ((event['country'] in ('JP', 'US') and event['stars'] >= 2)
                             or (event['country'] == 'EU' and event['stars'] >= 5))]
    
            usd = sum(1 for e in nk_events if e["currency"]=="USD")
            jpy = sum(1 for e in nk_events if e["currency"]=="JPY")
            eur = sum(1 for e in nk_events if e["currency"]=="EUR")
            print(f"파싱: {len(nk_events)}건 (JPY:{jpy} USD:{usd} EUR:{eur})")
            for ev in nk_events[:6]:
                print(f"  {ev['date']} {ev['time']} {ev['currency']} {ev['title'][:28]} | actual={ev['actual']}")
    
    except Exception as e:
        print(f"error: {e}")
        import traceback; traceback.print_exc()
    
    # ── ForexFactory JSON (미래 일정 보완) ──
    ff_items = []
    ff_urls = ["https://nfs.faireconomy.media/ff_calendar_thisweek.json",
               "https://nfs.faireconomy.media/ff_calendar_nextweek.json"] if include_forexfactory else []
    for url in ff_urls:
        try:
            res = requests.get(url, headers={"User-Agent":"Mozilla/5.0"}, timeout=15)
            if res.status_code == 200:
                payload = res.json()
                if isinstance(payload, list):
                    ff_items.extend(item for item in payload if isinstance(item, dict))
                    successful_sources += 1
        except: pass
    print(f"FF: {len(ff_items)}건")
    
    push_items = build_payload(nk_events, ff_items, now=datetime.now(JST))
    
    actual_cnt = sum(1 for p in push_items if released_actual(p["actual"]))
    print(f"총 push: {len(push_items)}건 (actual: {actual_cnt}건)")
    print(f"calendar observed_at={datetime.now(timezone.utc).isoformat(timespec='seconds')} "
          f"schedule_only={sum(p['result_status']=='schedule_only' for p in push_items)} "
          f"ff_schedule_fetch={include_forexfactory}")
    for p in push_items[:4]:
        print(f"  {p['date']} {p['time']} {p['currency']} {p['title'][:28]} | actual={p['actual']}")
    
    if push_items:
        print('Pushing calendar batch')
        result = push_json(VPS_URL,"/push/ff_events",{"items":push_items})
        print(f"VPS saved={result.get('saved',0)}")
    else:
        if not successful_sources:
            raise RuntimeError("All calendar sources failed")
        print("No calendar events")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--skip-forexfactory', action='store_true', help='Fetch only result-capable Nikkei; FF weekly exports are schedule supplements.')
    main(include_forexfactory=not parser.parse_args().skip_forexfactory)

