"""
collect_themes.py
GitHub Actions에서 실행 — 카부탄에서 종목 테마 수집 → VPS /push/themes
전종목 수집 (VPS stock_master 기준)
"""
import os, re, time, json, requests, sys
from datetime import datetime
from zoneinfo import ZoneInfo
from bs4 import BeautifulSoup

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


def fetch_kabutan_themes(code: str) -> list:
    """카부탄 종목 페이지에서 投資テーマ 파싱"""
    url = f"https://kabutan.jp/stock/?code={code}"
    try:
        r = SESSION.get(url, timeout=15)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, 'html.parser')
        heading = soup.select_one('#kobetsu')
        if heading is None or not re.search(r'\(' + re.escape(code) + r'\)', heading.get_text(' ', strip=True)):
            raise ValueError('Stock page identity could not be verified')
        theme_row = next((row for row in soup.select('tr')
                          if row.find('th') is not None and row.find('th').get_text(strip=True) == 'テーマ'), None)
        if theme_row is None or theme_row.find('td') is None:
            raise ValueError('Stock theme section was not found')
        cell = theme_row.find('td')
        anchors = [a for a in cell.select('a[href]') if a['href'].startswith('/themes/?theme=')]
        if not anchors:
            # A verified empty field is valid. Unknown HTML must never clear
            # existing themes and mark a security complete for seven days.
            if cell.get_text(' ', strip=True) in ('', '-', '－', '―', '—', 'なし', '該当なし'):
                return []
            raise ValueError('Stock theme section could not be parsed')
        theme_links = [a.get_text(' ', strip=True) for a in anchors]
        seen = set()
        result = []
        skip = {"TOPIXコア30","TOPIX100","日経225","JPX日経400",
                "東証プライム","東証スタンダード","東証グロース",
                "情報・通信業","電気機器","機械","化学","銀行業"}
        for t in theme_links:
            t = t.strip()
            if t and t not in seen and t not in skip and 2 <= len(t) <= 20:
                seen.add(t)
                result.append(t)
        return result[:10]
    except Exception as e:
        raise RuntimeError(f'Theme collection failed for {code}') from e


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
    for code in pending[:400]:
        if time.monotonic()>=deadline:
            break
        themes=fetch_kabutan_themes(code)
        batch.append({"code":code,"themes":themes,"source":"kabutan"})
        processed+=1
        if len(batch)>=25:
            push_to_vps(batch)
            batch=[]
        time.sleep(2)
    if batch:
        push_to_vps(batch)
    log(f"Theme batch complete: processed={processed}, remaining={len(pending)-processed}")


if __name__ == "__main__":
    main()
