# -*- coding: utf-8 -*-
"""
collect_tdnet.py — GitHub Actions에서 TDnet 공시 수집 → VPS push
소스: TDnet 직접 HTML (release.tdnet.info)
"""
import os, sys, json, re, requests
from datetime import datetime, timezone, timedelta

JST = timezone(timedelta(hours=9))
VPS_URL = os.environ.get("VPS_NEWS_API_URL", os.environ.get("VPS_URL", "https://jpstocklive.com"))
TIMEOUT = 30

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "text/html,*/*",
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

    # TDnet 직접 HTML 스크래핑
    for page in range(1, 6):  # 최대 5페이지
        url = f"https://www.release.tdnet.info/inbs/I_list_{page:03d}_{date_str}.html"
        try:
            r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
            if r.status_code != 200:
                break
            r.encoding = 'utf-8'
            html = r.text

            # 공시 행 파싱
            # <td class="...">시간</td><td>코드</td><td>회사명</td><td>제목</td>
            rows = re.findall(
                r'<td[^>]*class="[^"]*tm[^"]*"[^>]*>(\d{2}:\d{2})</td>'
                r'.*?<td[^>]*>(\d{4})</td>'
                r'.*?<td[^>]*>(.*?)</td>'
                r'.*?<td[^>]*><a href="([^"]+)"[^>]*>(.*?)</a>',
                html, re.DOTALL
            )
            for row in rows:
                time_str, code, company, link, title = row
                company = re.sub(r'<[^>]+>', '', company).strip()
                title = re.sub(r'<[^>]+>', '', title).strip()
                if not code or not title: continue
                disc_id = f"{date_str}_{code}_{time_str.replace(':','')}"
                full_url = f"https://www.release.tdnet.info/inbs/{link}" if link and not link.startswith('http') else link
                items.append({
                    "disclosure_id": disc_id,
                    "code": code[:4],
                    "company_name": company,
                    "title": title,
                    "rank": _rank(title),
                    "disclosed_at": f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]} {time_str}:00",
                    "time_str": time_str,
                    "url": full_url,
                })
            print(f"  페이지 {page}: {len(rows)}건")
            if len(rows) < 50: break  # 마지막 페이지
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
