"""
fetch_kessan.py (최종)
- kabuyoho.jp  : 당일 결산 (종목명 + 결산종류 포함)
- nikkei225jp  : 미래 2주치 日経225 결산예정
두 소스 합산 → VPS /push/kessan
"""
import os, sys, re, requests
from datetime import datetime, timedelta, timezone

JST = timezone(timedelta(hours=9))
VPS_BASE_URL    = os.environ.get("VPS_BASE_URL", "https://jpstocklive.com")
VPS_PUSH_SECRET = os.environ.get("VPS_PUSH_SECRET", "")

HEADERS_SP = {
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
    "Accept-Language": "ja,en;q=0.9",
}
HEADERS_PC = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120",
    "Accept-Language": "ja,en;q=0.9",
}

# ── 소스1: kabuyoho 당일 결산 ────────────────────────────────
def fetch_kabuyoho() -> list:
    try:
        res = requests.get("https://kabuyoho.jp/sp/calender", headers=HEADERS_SP, timeout=15)
        if res.status_code != 200:
            print(f"  kabuyoho HTTP {res.status_code}")
            return []
        html = res.text
    except Exception as e:
        print(f"  kabuyoho 오류: {e}")
        return []

    now = datetime.now(JST)
    items = []
    seen = set()

    cards = re.findall(
        r'href="/sp/reportTop\?bcode=(\d{4})".*?'
        r'<p>\s*([^<\n]{1,20}?)\s*<br>.*?'
        r'class="nmbr">\d{4}</span>.*?'
        r'<span[^>]*>\s*(1Q|2Q|3Q|4Q|本決算|中間|通期|本)\s*</span>.*?'
        r'(\d{4}/\d{2}/\d{2})',
        html, re.DOTALL
    )
    for code, name, ktype, date_raw in cards:
        try:
            kessan_date = datetime.strptime(date_raw, "%Y/%m/%d").strftime("%Y-%m-%d")
        except:
            kessan_date = now.strftime("%Y-%m-%d")
        key = f"{code}_{kessan_date}"
        if key in seen:
            continue
        seen.add(key)
        items.append({
            "code": code[:4], "name": name.strip()[:20],
            "market": "", "fiscal_period": ktype.strip(),
            "kessan_date": kessan_date, "kessan_time": "",
            "source": "kabuyoho",
        })

    print(f"  kabuyoho: {len(items)}건 (당일)")
    return items

# ── 소스2: nikkei225jp 미래 2주치 ────────────────────────────
def fetch_nikkei225jp() -> list:
    try:
        res = requests.get("https://nikkei225jp.com/schedule/", headers=HEADERS_PC, timeout=15)
        res.raise_for_status()
        html = res.text
    except Exception as e:
        print(f"  nikkei225jp 오류: {e}")
        return []

    now = datetime.now(JST)
    m = re.search(r'決算予定[^\n]*日経225(.*?)(?=決算予定[^\n]*(?:米|S&P)|市場休日)', html, re.DOTALL)
    if not m:
        print("  nikkei225jp: 섹션 없음")
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

    print(f"  nikkei225jp: {len(items)}건 (2주치)")
    return items

def push_to_vps(items):
    r = requests.post(f"{VPS_BASE_URL}/push/kessan",
                      json={"items": items, "secret": VPS_PUSH_SECRET}, timeout=30)
    if r.status_code == 200:
        j = r.json()
        print(f"  ✅ push: {j.get('saved',0)}건 저장 / {j.get('total',0)}건")
    else:
        print(f"  ❌ push 실패: {r.status_code} {r.text[:100]}")
        sys.exit(1)

def main():
    now = datetime.now(JST)
    print(f"=== 결산예정 수집 ({now.strftime('%Y-%m-%d %H:%M JST')}) ===")

    items_kb  = fetch_kabuyoho()
    items_n25 = fetch_nikkei225jp()

    # 중복 제거: kabuyoho 우선 (결산종류 포함)
    seen = {f"{it['code']}_{it['kessan_date']}" for it in items_kb}
    for it in items_n25:
        k = f"{it['code']}_{it['kessan_date']}"
        if k not in seen:
            seen.add(k)
            items_kb.append(it)

    items = items_kb
    print(f"\n합계: {len(items)}건")

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
