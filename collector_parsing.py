"""Article identity and source timestamps; never invent a publication time."""
from datetime import datetime, timezone, timedelta
import re
from urllib.parse import unquote, urljoin
from bs4 import BeautifulSoup

JST = timezone(timedelta(hours=9))
STOCK_CODE_PATTERN = r'(?:[0-9]{3}[A-Z]|[0-9]{4})(?![0-9A-Z])'


def stock_code(value):
    """Japanese listed security codes contain four characters."""
    match = re.search(r'(?:[?&]code=|/stock/|[?&]bcode=)(' + STOCK_CODE_PATTERN + ')', value)
    if not match:
        match = re.search(r'data-code=[\"\'](' + STOCK_CODE_PATTERN + r')[\"\']', value)
    return match.group(1) if match else ''


def article_timestamp(container, href=''):
    """Use only the article's own time tag or dated Kabutan article URL."""
    for tag in container.select('time[datetime]'):
        try:
            parsed = datetime.fromisoformat(tag['datetime'].replace('Z', '+00:00'))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=JST)
            return parsed.astimezone(JST)
        except (TypeError, ValueError):
            continue
    # Kabutan document identifiers include YYYYMMDD. The suffix is a sequence,
    # not HHMM, so a clock can come only from the same article row.
    dated = re.search(r'[?&]b=[nk]([0-9]{8})[0-9]*(?:&|$)', unquote(href))
    if not dated:
        return None
    clock = re.search(r'(?<![0-9])([0-9]{1,2}):([0-9]{2})(?![0-9])', container.get_text(' ', strip=True))
    try:
        date = datetime.strptime(dated.group(1), '%Y%m%d').replace(tzinfo=JST)
        return date.replace(hour=int(clock.group(1)), minute=int(clock.group(2))) if clock else date
    except ValueError:
        return None


def kabutan_articles(html):
    """News rows only: stock rankings are not financial news releases."""
    soup = BeautifulSoup(html, 'html.parser')
    seen = set()
    for row in soup.select('tr'):
        anchor = next((a for a in row.select('a[href]') if a['href'].startswith('/news/')
                       and re.search(r'[?&]b=[nk][0-9]{8}', a['href'])), None)
        if anchor is None:
            continue
        title = anchor.get_text(' ', strip=True)
        href = anchor['href']
        published = article_timestamp(row, href)
        if not title or published is None or href in seen:
            continue
        seen.add(href)
        code = stock_code(str(row)) or stock_code(href)
        if not code:
            bracket = re.search(r'[\[＜<](' + STOCK_CODE_PATTERN + r')[\]＞>]', title)
            code = bracket.group(1) if bracket else ''
        yield dict(title=title, url=urljoin('https://kabutan.jp', href), code=code,
                   published_at=published.strftime('%Y-%m-%d %H:%M:%S'),
                   date=published.strftime('%Y-%m-%d'), time=published.strftime('%H:%M'))
