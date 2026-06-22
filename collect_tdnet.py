# -*- coding: utf-8 -*-
"""
collect_tdnet.py — GitHub Actions에서 TDnet 공시 수집 → VPS push
소스: TDnet 직접 HTML (release.tdnet.info)
"""
import os, sys, re, requests
from datetime import datetime, timezone, timedelta
from bs4 import BeautifulSoup

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

def fetch_tdnet():
    now_jst = datetime.now(JST)
    date_str = now_jst.strftime("%Y%m%d")
    items = []

    for page in range(1, 6):
        url = f"https://www.release.tdnet.info/inbs/I_list_{page:03d}_{date_str}.html"
        try:
            r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
            if r.status_code != 200:
                print(f"  페이지 {page}: HTTP {r.status_code}")
                break
            r.encoding = 'utf-8'
            soup = BeautifulSoup(r.text, 'html.parser')

            # 디버그: 테이블 구조 확인
            if page == 1:
                tables = soup.find_all('table')
                print(f"  [디버그] 테이블 수: {len(tables)}")
                rows_all = soup.find_all('tr')
                print(f"  [디버그] tr 수: {len(rows_all)}")
                if rows_all:
                    print(f"  [디버그] 첫 tr: {str(rows_all[0])[:200]}")

            # 공시 테이블 행 파싱
            rows = soup.find_all('tr')
            page_count = 0
            for row in rows:
                tds = row.find_all('td')
                if len(tds) < 5:
                    continue
                # 시간(HH:MM), 코드(4자리), 회사명, 제목 순서 파악
                texts = [td.get_text(strip=True) for td in tds]
                # 시간 패턴 찾기
                time_str = ""
                code = ""
                company = ""
                title = ""
                link = ""
                for i, td in enumerate(tds):
                    t = td.get_text(strip=True)
                    if re.match(r'^\d{2}:\d{2}$', t):
                        time_str = t
                    elif re.match(r'^\d{4}$', t) and not code:
                        code = t
                    elif td.find('a') and not title:
                        a = td.find('a')
                        title = a.get_text(strip=True)
                        href = a.get('href', '')
                        link = f"https://www.release.tdnet.info/inbs/{href}" if href and not href.startswith('http') else href
                    elif code and time_str and not company and t and not re.match(r'^\d', t):
                        company = t

                if not code or not title or not time_str:
                    continue

                disc_id = f"{date_str}_{code}_{time_str.replace(':','')}"
                items.append({
                    "disclosure_id": disc_id,
                    "code": code[:4],
                    "company_name": company,
                    "title": title,
                    "rank": _rank(title),
                    "disclosed_at": f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]} {time_str}:00",
                    "time_str": time_str,
                    "url": link,
                })
                page_count += 1

            print(f"  페이지 {page}: {page_count}건")
            if page_count < 50:
                break
        except Exception as e:
            print(f"⚠️ 페이지 {page}: {e}")
            break

    return items

def push_to_vps(items):
    if not items:
        print("전송할 공시 없음")
        return
    try:
        r = requests.post(
            f"{VPS_URL}/push/tdnet",
            json={"items": items},
            timeout=30
        )
        result = r.json()
        print(f"✅ VPS push: {result.get('saved', 0)}건 저장 / {result.get('total', 0)}건 전달")
    except Exception as e:
        print(f"❌ VPS push 실패: {e}")
        sys.exit(1)

if __name__ == "__main__":
    print(f"[TDnet] 수집 시작 {datetime.now(JST).strftime('%Y-%m-%d %H:%M JST')}")
    items = fetch_tdnet()
    print(f"[TDnet] 수집: {len(items)}건")
    push_to_vps(items)
