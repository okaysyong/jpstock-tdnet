# -*- coding: utf-8 -*-
"""
collect_tdnet.py — GitHub Actions에서 TDnet 공시 수집 → VPS push
소스: TDnet 직접 HTML (release.tdnet.info)
"""
import os, sys, re, requests
from datetime import datetime, timezone, timedelta
from bs4 import BeautifulSoup
from collector_common import canonical_disclosure_id

JST = timezone(timedelta(hours=9))
VPS_URL = os.environ.get("VPS_NEWS_API_URL", os.environ.get("VPS_URL", "https://jpstocklive.com"))
TIMEOUT = 30

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,*/*",
    "Accept-Language": "ja,en;q=0.9",
}

def _rank(title: str) -> int:
    t = title or ""
    if any(k in t for k in ["決算短信", "業績予想の修正", "配当予想の修正", "TOB", "MBO",
                              "公開買付", "自己株式取得", "合併", "分割", "上場廃止",
                              "民事再生", "破産", "第三者割当"]):
        return 4
    if any(k in t for k in ["業績", "配当", "株式", "取得", "売却", "子会社", "資本"]):
        return 3
    if any(k in t for k in ["契約", "提携", "受注", "開発", "新製品", "人事"]):
        return 2
    return 1

def _confirmed_empty_page(soup, date_str):
    """Accept only TDnet's dated no-disclosures page, never arbitrary HTML.

    Official template verified on 2026-10-03. Empty days have no
    main-list-table; their date and explicit message are separate elements.
    """
    expected = f'{date_str[:4]}年{date_str[4:6]}月{date_str[6:]}日'
    title = soup.find('title')
    header = soup.find(id='kaiji-info-box-top')
    main = soup.find(id='main-list')
    dates = soup.find_all(id='kaiji-date-1')
    messages = soup.find_all(id='kaiji-text-1')
    return bool(title and title.get_text(strip=True) == '適時開示情報閲覧サービス - 開示情報一覧'
                and soup.find(id='list-body-box') and header and main
                and len(dates) == 1 and len(messages) == 1
                and header.find(id='kaiji-date-1') is dates[0]
                and header.find(id='kaiji-text-1') is messages[0]
                and dates[0].get_text(strip=True) == expected
                and messages[0].get_text(strip=True) == 'に開示された情報はありません。'
                and not main.get_text(strip=True) and not main.find(['table', 'a', 'iframe'])
                and soup.find(id='main-list-table') is None)


def fetch_tdnet(now=None):
    now_jst = (now or datetime.now(JST)).astimezone(JST)
    date_str = now_jst.strftime("%Y%m%d")
    items = []

    for page in range(1, 51):
        url = f"https://www.release.tdnet.info/inbs/I_list_{page:03d}_{date_str}.html"
        try:
            r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
            if r.status_code == 404:
                if page == 1:
                    raise RuntimeError('TDnet first page unavailable')
                break
            r.raise_for_status()
            r.encoding = 'utf-8'
            soup = BeautifulSoup(r.text, 'html.parser')

            # main-list-table에서 공시 파싱
            main_tbl = soup.find('table', id='main-list-table')
            if not main_tbl:
                if page == 1 and not items and _confirmed_empty_page(soup, date_str):
                    print(f'  TDnet {date_str}: confirmed no disclosures')
                    return []
                raise RuntimeError('TDnet table not found')

            page_count = 0
            for row in main_tbl.find_all('tr'):
                time_td   = row.find('td', class_=re.compile('kjTime'))
                code_td   = row.find('td', class_=re.compile('kjCode'))
                name_td   = row.find('td', class_=re.compile('kjName'))
                title_td  = row.find('td', class_=re.compile('kjTitle'))
                if not (time_td and code_td and title_td):
                    continue
                time_str = time_td.get_text(strip=True)
                code     = code_td.get_text(strip=True)[:4]
                company  = name_td.get_text(strip=True) if name_td else ""
                a_tag    = title_td.find('a')
                if not a_tag: continue
                title    = a_tag.get_text(strip=True)
                href     = a_tag.get('href', '')
                link     = f"https://www.release.tdnet.info/inbs/{href}" if href and not href.startswith('http') else href
                if not code or not title: continue
                disc_id = canonical_disclosure_id({'stock_code':code,'title':title,'pdf_url':link,
                    'disclosed_at':f'{date_str[:4]}-{date_str[4:6]}-{date_str[6:]} {time_str}:00'})
                items.append({
                    "disclosure_id": disc_id,
                    "stock_code": code,
                    "company_name": company,
                    "title": title,
                    "rank": _rank(title),
                    "disclosed_at": f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]} {time_str}:00",
                    "time_str": time_str,
                    "pdf_url": link,
                })
                page_count += 1
            if page_count == 0:
                raise RuntimeError('TDnet table contained no valid disclosures')
            print(f"  페이지 {page}: {page_count}건")
            if page_count < 50:
                break
        except Exception as e:
            raise RuntimeError(f'TDnet page {page} collection failed') from e

    return items

def push_to_vps(items):
    from collector_common import push_json
    if not items:
        return {"ok":True,"saved":0,"total":0}
    return push_json(VPS_URL,"/push/tdnet",{"items":items})

if __name__ == "__main__":
    print(f"[TDnet] 수집 시작 {datetime.now(JST).strftime('%Y-%m-%d %H:%M JST')}")
    items = fetch_tdnet()
    print(f"[TDnet] 수집: {len(items)}건")
    push_to_vps(items)
