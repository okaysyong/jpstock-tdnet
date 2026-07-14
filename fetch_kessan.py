"""
fetch_kessan.py (v5)
소스 우선순위:
  1. kabutan.jp/warning/?mode=2_1  — 시간 + 결산종류 + 전종목
  2. nikkei225jp.com/schedule/     — fallback (日経225만)
"""
import os, sys, re, requests
from datetime import datetime, timedelta, timezone

JST = timezone(timedelta(hours=9))
VPS_BASE_URL    = os.environ.get("VPS_BASE_URL", "https://jpstocklive.com")
VPS_PUSH_SECRET = os.environ.get("VPS_PUSH_SECRET", "")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120",
    "Accept-Language": "ja,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# ── 소스1: kabutan.jp 결산予定 ──────────────────────────────
def fetch_kabutan(days: int = 14) -> list:
    """
    https://kabutan.jp/warning/?mode=2_1&select=1
    발표일 / 시간 / 종목코드 / 종목명 / 결산종류 수집
    """
    now = datetime.now(JST)
    items = []
    seen = set()

    for delta in range(days):
        target = now + timedelta(days=delta)
        if target.weekday() >= 5:
            continue
        date_str = target.strftime("%Y%m%d")
        url = f"https://kabutan.jp/warning/?mode=2_1&select=1&of=0&ymd={date_str}"

        try:
            res = requests.get(url, headers=HEADERS, timeout=15)
            if res.status_code != 200:
                print(f"  kabutan {date_str}: HTTP {res.status_code}")
                continue
            html = res.text
        except Exception as e:
            print(f"  kabutan {date_str} 오류: {e}")
            continue

        # 테이블 행 파싱
        # <td>15:30</td> ... <a href="/stock/forecast/?code=6532">ベイカレント</a> ... <td>1Q</td>
        rows = re.findall(
            r'<tr[^>]*>\s*<td[^>]*>(\d{1,2}:\d{2})</td>'   # 시간
            r'.*?/stock/forecast/\?code=(\d{4})'             # 코드
            r'[^>]*>([^<]+)</a>'                             # 종목명
            r'.*?<td[^>]*>([^<]*(?:1Q|2Q|3Q|4Q|本決算|中間|通期)[^<]*)</td>',  # 결산종류
            html, re.DOTALL
        )

        kessan_date = target.strftime("%Y-%m-%d")
        for time_str, code, name, ktype in rows:
            key = f"{code}_{kessan_date}"
            if key in seen:
                continue
            seen.add(key)
            items.append({
                "code":          code[:4],
                "name":          name.strip()[:20],
                "market":        "",
                "fiscal_period": ktype.strip()[:20],
                "kessan_date":   kessan_date,
                "kessan_time":   time_str.strip(),
                "source":        "kabutan",
            })

        print(f"  kabutan {date_str}: {len([x for x in items if x['kessan_date']==kessan_date])}건")

    return items


# ── 소스2: nikkei225jp fallback ─────────────────────────────
def fetch_nikkei225jp() -> list:
    url = "https://nikkei225jp.com/schedule/"
    try:
        res = requests.get(url, headers=HEADERS, timeout=15)
        res.raise_for_status()
        html = res.text
    except Exception as e:
        print(f"  nikkei225jp 실패: {e}")
        return []

    now = datetime.now(JST)
    current_year = now.year

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
        stocks = re.findall(
            r'href=(?:")?(?:https?:)?//finance\.yahoo\.co\.jp/quote/(\d{4})\.T[^">\s]*(?:")?[^>]*>\s*([^<(]+?)\s*(?:</a>|\()',
            part
        )
        for code, name in stocks:
            name = name.strip()
            if not name:
                continue
            items.append({
                "code":          code[:4],
                "name":          name[:20],
                "market":        "日経225",
                "fiscal_period": "",
                "kessan_date":   current_date,
                "kessan_time":   "",
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

    # 소스1: kabutan (시간+결산종류 포함)
    print("\n[소스1] kabutan.jp 수집 중 (14일치)...")
    items = fetch_kabutan(days=14)
    print(f"  소계: {len(items)}건")

    # 소스1 실패 시 fallback
    if not items:
        print("\n[소스2] nikkei225jp fallback 수집 중...")
        items = fetch_nikkei225jp()
        print(f"  소계: {len(items)}건")

    print(f"\n총 {len(items)}건 수집")
    if not items:
        print("  ⚠️ 데이터 없음")
        sys.exit(0)

    for it in items[:5]:
        print(f"  {it['kessan_date']} {it['kessan_time']} [{it['code']}] {it['name']} {it['fiscal_period']}")
    if len(items) > 5:
        print(f"  ... 외 {len(items)-5}건")

    push_to_vps(items)
    print("=== 완료 ===")

if __name__ == "__main__":
    main()
