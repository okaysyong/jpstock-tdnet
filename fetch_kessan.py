"""
fetch_kessan.py (v2)
====================
nikkei225jp.com/schedule/ → 日経225 결산예정 크롤링 → VPS push
GitHub Actions에서 매일 06:00 JST 실행
"""

import os, sys, re, requests
from datetime import datetime, timedelta, timezone

JST = timezone(timedelta(hours=9))
VPS_BASE_URL   = os.environ.get("VPS_BASE_URL", "https://jpstocklive.com")
VPS_PUSH_SECRET = os.environ.get("VPS_PUSH_SECRET", "")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120",
    "Accept-Language": "ja,en;q=0.9",
}

def fetch_kessan_nikkei225jp() -> list:
    """nikkei225jp.com/schedule/ から日経225決算予定をパース"""
    url = "https://nikkei225jp.com/schedule/"
    try:
        res = requests.get(url, headers=HEADERS, timeout=15)
        res.raise_for_status()
        html = res.text
    except Exception as e:
        print(f"  ❌ 취득 실패: {e}")
        return []

    items = []
    now = datetime.now(JST)
    current_year = now.year

    # 결산 섹션 추출: "決算予定 日経225" ~ "決算予定 米S&P500"
    m = re.search(
        r'決算予定\s*日経225.*?(?=決算予定\s*米S&P500|市場休日)',
        html, re.DOTALL
    )
    if not m:
        print("  ⚠️ 日経225 결산예정 섹션 없음")
        return []

    section = m.group(0)

    # 날짜 블록 파싱: "07/15(水)" 형태
    date_blocks = re.split(r'(\d{2}/\d{2}\([月火水木金土日]\))', section)

    current_date = None
    for part in date_blocks:
        # 날짜 헤더
        dm = re.match(r'(\d{2})/(\d{2})\([月火水木金土日]\)', part.strip())
        if dm:
            mo, dy = int(dm.group(1)), int(dm.group(2))
            # 연도 처리 (12월→1월 크로스)
            year = current_year
            if now.month == 12 and mo == 1:
                year = current_year + 1
            try:
                current_date = datetime(year, mo, dy).strftime("%Y-%m-%d")
            except:
                current_date = None
            continue

        if not current_date:
            continue

        # 종목명 + 코드 추출
        # Yahoo Finance 링크: /quote/7203.T
        stocks = re.findall(
            r'href="https://finance\.yahoo\.co\.jp/quote/(\d{4})\.T[^"]*"[^>]*>\s*([^<]+?)\s*</a>',
            part
        )
        for code, name in stocks:
            name = name.strip()
            if not name or name == '-':
                continue
            items.append({
                "code":          code[:4],
                "name":          name[:20],
                "market":        "日経225",
                "fiscal_period": "",        # 페이지에 기재 없음
                "kessan_date":   current_date,
                "kessan_time":   "",        # 시간 미기재
                "source":        "nikkei225jp",
            })

    return items

def push_to_vps(items: list):
    url = f"{VPS_BASE_URL}/push/kessan"
    payload = {"items": items, "secret": VPS_PUSH_SECRET}
    try:
        res = requests.post(url, json=payload, timeout=30)
        if res.status_code == 200:
            j = res.json()
            print(f"  ✅ VPS push: {j.get('saved',0)}건 저장 / {j.get('total',0)}건 수신")
        else:
            print(f"  ❌ VPS push 실패: HTTP {res.status_code} — {res.text[:200]}")
            sys.exit(1)
    except Exception as e:
        print(f"  ❌ VPS push 오류: {e}")
        sys.exit(1)

def main():
    now = datetime.now(JST)
    print(f"=== 결산예정 수집 시작 ({now.strftime('%Y-%m-%d %H:%M JST')}) ===")
    print("  소스: nikkei225jp.com/schedule/ (日経225)")

    items = fetch_kessan_nikkei225jp()
    print(f"  수집: {len(items)}건")

    if not items:
        print("  ⚠️ 데이터 없음")
        sys.exit(0)

    # 샘플 출력
    for it in items[:5]:
        print(f"    {it['kessan_date']} [{it['code']}] {it['name']}")
    if len(items) > 5:
        print(f"    ... 외 {len(items)-5}건")

    print(f"\n  VPS push 중...")
    push_to_vps(items)
    print("=== 완료 ===")

if __name__ == "__main__":
    main()
