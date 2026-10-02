"""
collect_themes.py
GitHub Actions에서 실행 — 카부탄에서 종목 테마 수집 → VPS /push/themes
전종목 수집 (VPS stock_master 기준)
"""
import os, re, time, json, requests, sys
from datetime import datetime
from zoneinfo import ZoneInfo
from bs4 import BeautifulSoup
from urllib.parse import urlparse, parse_qs

JST = ZoneInfo("Asia/Tokyo")
VPS_API_URL = os.environ.get("VPS_NEWS_API_URL", "")
VPS_TOKEN   = os.environ.get("VPS_TOKEN", "")

def log(msg):
    print(msg, flush=True)

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ja-JP,ja;q=0.9,en-US;q=0.8",
    "Connection": "keep-alive",
})


def parse_kabutan_themes(html: str, code: str) -> list:
    """Read only the identified security's desktop/mobile theme section."""
    if not re.fullmatch(r'[0-9][0-9A-Z]{3}', code):
        raise ValueError('Invalid security code')
    soup = BeautifulSoup(html, 'html.parser')
    heading = soup.select_one('#kobetsu')
    if heading is not None:
        if not re.search(r'\(' + re.escape(code) + r'\)', heading.get_text(' ', strip=True)):
            raise ValueError('Stock page identity could not be verified')
        row = next((row for row in soup.select('tr') if row.find('th') is not None
                    and row.find('th').get_text(strip=True) == 'テーマ'), None)
        cell = row.find('td') if row else None
        mobile = False
    else:
        # Mobile h1 contains the name but not the code. Both canonical URL and
        # the title must explicitly agree on the requested security.
        canonical = soup.select_one('link[rel="canonical"]')
        identity = urlparse(canonical.get('href', '') if canonical else '')
        title = soup.title.get_text(' ', strip=True) if soup.title else ''
        if (identity.scheme != 'https' or identity.netloc != 'kabutan.jp'
                or identity.path != '/stock/' or parse_qs(identity.query).get('code') != [code]
                or not re.search(r'【' + re.escape(code) + r'】', title)):
            raise ValueError('Mobile stock identity could not be verified')
        rows = [row for row in soup.select('[data-controller~="stocks--basic-info"]')
                if any(child.get_text(' ', strip=True) == '関連テーマ'
                       for child in row.find_all(recursive=False))]
        cells = [cell for row in rows for cell in
                 row.select('[data-stocks--basic-info-target="themeContainer"]')]
        if len(cells) != 1:
            raise ValueError('Mobile theme section missing or ambiguous')
        cell, mobile = cells[0], True
    if cell is None:
        raise ValueError('Stock theme section was not found')
    anchors = [a for a in cell.select('a[href]') if
               (re.fullmatch(r'/themes/[^/?#]+/', a['href']) if mobile
                else a['href'].startswith('/themes/?theme='))]
    if not anchors:
        if cell.get_text(' ', strip=True) in ('', '-', '－', '―', '—', 'なし', '該当なし'):
            return []
        raise ValueError('Stock theme section could not be parsed')
    skip = {"TOPIXコア30", "TOPIX100", "日経225", "JPX日経400",
            "東証プライム", "東証スタンダード", "東証グロース",
            "情報・通信業", "電気機器", "機械", "化学", "銀行業"}
    result = []
    for anchor in anchors:
        text = anchor.get_text(' ', strip=True)
        if text not in result and text not in skip and 2 <= len(text) <= 20:
            result.append(text)
    return result[:10]


class ThemeAccessDenied(RuntimeError):
    """Stop this batch when the provider explicitly denies or rate-limits it."""


def fetch_kabutan_themes(code: str) -> list:
    """A public mobile stock page is the fallback for unavailable desktop HTML."""
    if not re.fullmatch(r'[0-9][0-9A-Z]{3}', code):
        raise RuntimeError('Invalid security code')
    last = None
    for url in (f'https://kabutan.jp/stock/?code={code}', f'https://s.kabutan.jp/stocks/{code}/'):
        try:
            response = SESSION.get(url, timeout=(4, 8), allow_redirects=False)
            # Do not follow authentication redirects or retry an explicit
            # access/rate-limit rejection through another host.
            if response.status_code in (401, 403, 429):
                raise PermissionError('Provider declined this collection request')
            response.raise_for_status()
            if response.status_code != 200 or len(response.text.encode('utf-8')) > 2 * 1024 * 1024:
                raise ValueError('Unexpected or oversized source response')
            return parse_kabutan_themes(response.text, code)
        except PermissionError as exc:
            raise ThemeAccessDenied(f'Theme collection denied for {code}') from exc
        except (requests.RequestException, ValueError) as exc:
            last = exc
    raise RuntimeError(f'Theme collection failed for {code}') from last


def get_all_codes_from_vps() -> list:
    from collector_common import get_json
    data=get_json(VPS_API_URL,"/stock_master",session=SESSION)
    codes=sorted({str(item["code"]) for item in data.get("items",[]) if item.get("code")})
    if not codes:
        raise RuntimeError("Stock master is empty")
    return codes


def get_already_done_from_vps() -> set:
    from collector_common import get_json
    return set(get_json(VPS_API_URL,"/themes/collected?max_age_days=7",session=SESSION).get("codes",[]))


def push_to_vps(items: list):
    from collector_common import push_json
    if items:
        return push_json(VPS_API_URL,"/push/themes",{"items":items},session=SESSION)
    return {"ok":True,"saved":0,"total":0}


def main():
    codes=get_all_codes_from_vps()
    done=get_already_done_from_vps()
    pending=[code for code in codes if code not in done]
    deadline=time.monotonic()+2400
    batch=[]
    processed=0
    failed=0
    for code in pending[:400]:
        if time.monotonic()>=deadline:
            break
        try:
            themes=fetch_kabutan_themes(code)
        except ThemeAccessDenied:
            failed+=1
            log('Theme provider access/rate limit response; remaining requests deferred')
            break
        except RuntimeError:
            failed+=1
            log(f'Theme source unavailable: code={code}; existing cache preserved')
            time.sleep(2)
            continue
        batch.append({"code":code,"themes":themes,"source":"kabutan"})
        processed+=1
        if len(batch)>=25:
            push_to_vps(batch)
            batch=[]
        time.sleep(2)
    if batch:
        push_to_vps(batch)
    log(f"Theme batch complete: processed={processed}, failed={failed}, remaining={len(pending)-processed}")
    if failed and not processed:
        raise RuntimeError('No themes could be verified; existing VPS data was preserved')


if __name__ == "__main__":
    main()
