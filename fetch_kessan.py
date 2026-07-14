"""
fetch_kessan.py (v7)
소스 우선순위:
  1. kabuyoho.jp/sp/calender — 시간+결산종류+전종목 (정적 HTML)
  2. nikkei225jp.com/schedule/ — fallback (日経225만)
"""
import os, sys, re, requests
from datetime import datetime, timedelta, timezone

JST = timezone(timedelta(hours=9))
VPS_BASE_URL    = os.environ.get("VPS_BASE_URL", "https://jpstocklive.com")
VPS_PUSH_SECRET = os.environ.get("VPS_PUSH_SECRET", "")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
    "Accept-Language": "ja,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# ── 소스1: kabuyoho.jp 결산카렌더 ────────────────────────────
def fetch_kabuyoho() -> list:
    """
    https://kabuyoho.jp/sp/calender
    발표일 / 종목코드 / 종목명 / 결산종류 수집
    """
    url = "https://kabuyoho.jp/sp/calender"
    try:
        res = requests.get(url, headers=HEADERS, timeout=15)
        print(f"  kabuyoho HTTP {res.status_code}, 크기: {len(res.text)}자")
        if res.status_code != 200:
            return []
        html = res.text
    except Exception as e:
        print(f"  kabuyoho 오류: {e}")
        return []

    items = []
    seen = set()
    now = datetime.now(JST)
    current_year = now.year

    # 날짜 블록 분리
    # 패턴: "7月15日(水)" 형태
    date_blocks = re.split(r'(\d{1,2}月\d{1,2}日\([月火水木金]\))', html)

    current_date = None
    for part in date_blocks:
        dm = re.match(r'(\d{1,2})月(\d{1,2})日\([月火水木金]\)', part.strip())
        if dm:
            mo, dy = int(dm.group(1)), int(dm.group(2))
            year = current_year
            if now.month >= 11 and mo <= 2:
                year = current_year + 1
            try:
                current_date = datetime(year, mo, dy).strftime("%Y-%m-%d")
            except:
                current_date = None
            continue

        if not current_date:
            continue

        # 종목 파싱: 코드 4자리 + 종목명 + 결산종류
        rows = re.findall(
            r'(\d{4})[A-Z]?</[^>]+>\s*<[^>]+>([^<]{2,15})</[^>]+>'
            r'.*?(1Q|2Q|3Q|4Q|本決算|中間|通期|本$)',
            part, re.DOTALL
        )
        # 대안 패턴
        if not rows:
            rows = re.findall(
                r'code=(\d{4})[^>]*>([^<]{2,15})</a>'
                r'.*?(1Q|2Q|3Q|4Q|本決算|中間|通期)',
                part, re.DOTALL
            )

        day_count = 0
        for code, name, ktype in rows:
            key = f"{code}_{current_date}"
            if key in seen:
                continue
            seen.add(key)
            items.append({
                "code":          code[:4],
                "name":          name.strip()[:20],
                "market":        "",
                "fiscal_period": ktype.strip()[:20],
                "kessan_date":   current_date,
                "kessan_time":   "",
                "source":        "kabuyoho",
            })
            day_count += 1

        if day_count:
            print(f"  {current_date}: {day_count}건")

    return items


# ── 소스2: nikkei225jp fallback ─────────────────────────────
def fetch_nikkei225jp() -> list:
    url = "https://nikkei225jp.com/schedule/"
    h = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120",
        "Accept-Language": "ja,en;q=0.9",
    }
    try:
        res = requests.get(url, headers=h, timeout=15)
        res.raise_for_status()
        html = res.text
    except Exception as e:
        print(f"  nikkei225jp 실패: {e}")
        return []

    now = datetime.now(JST)
    m = re.search(
        r'決算予定[^\n]*日経225(.*?)(?=決算予定[^\n]*(?:米|S&P)|市場休日)',
        html, re.DOTALL
    )
    if not m:
        return []

    section = m.group(1)
    date_blocks = re.split(r'(\d{2}/\d{2}\([月火水木金土日]\))', section)
    items = []
    current_date = None
    for part in date_blocks:
        dm = re.match(r'(\d{2})/(\d{2})\([月火水木金土日]\)', part.strip())
        if dm:
            mo, dy = int(dm.group(1)), int(dm.group(2))
            year = now.year
            if now.month == 12 and mo == 1:
                year += 1
            try:
                current_date = datetime(year, mo, dy).strftime("%Y-%m-%d")
            except:
                current_date = None
            continue
        if not current_date:
            continue
        stocks = re.findall(
            r'href=(?:")?(?:https?:)?//finance\.yahoo\.co\.jp/quote/(\d{4})\.T[^">\s]*(?:")?[^>]*>\s*([^<(]+?)\s*(?:</a>|\()',
            part
        )
        for code, name in stocks:
            name = name.strip()
            if not name:
                continue
            items.append({
                "code": code[:4], "name": name[:20],
                "market": "日経225", "fiscal_period": "",
                "kessan_date": current_date, "kessan_time": "",
                "source": "nikkei225jp",
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

    print("\n[소스1] kabuyoho.jp 수집 중...")
    items = fetch_kabuyoho()
    print(f"  소계: {len(items)}건")

    if not items:
        print("\n[소스2] nikkei225jp fallback 수집 중...")
        items = fetch_nikkei225jp()
        print(f"  소계: {len(items)}건")

    print(f"\n총 {len(items)}건 수집")
    if not items:
        print("  ⚠️ 데이터 없음")
        sys.exit(0)

    for it in items[:5]:
        print(f"  {it['kessan_date']} [{it['code']}] {it['name']} {it['fiscal_period']}")
    if len(items) > 5:
        print(f"  ... 외 {len(items)-5}건")

    push_to_vps(items)
    print("=== 완료 ===")

if __name__ == "__main__":
    main()
