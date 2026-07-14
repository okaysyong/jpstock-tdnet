import os, sys, re, requests
from datetime import datetime, timedelta, timezone

JST = timezone(timedelta(hours=9))
VPS_BASE_URL    = os.environ.get("VPS_BASE_URL", "https://jpstocklive.com")
VPS_PUSH_SECRET = os.environ.get("VPS_PUSH_SECRET", "")

HEADERS_SP = {
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
    "Accept-Language": "ja,en;q=0.9",
}

def fetch_kabuyoho() -> list:
    url = "https://kabuyoho.jp/sp/calender"
    try:
        res = requests.get(url, headers=HEADERS_SP, timeout=15)
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

    # 카드 단위 파싱
    # 패턴: bcode=XXXX → 종목명 → 결산종류(1Q/2Q/3Q/本/中間/通期) → 発表日: YYYY/MM/DD
    cards = re.findall(
        r'href="/sp/reportTop\?bcode=(\d{4})".*?'   # 종목코드
        r'<p>\s*([^<\n]{1,20}?)\s*<br>.*?'           # 종목명
        r'class="nmbr">\d{4}</span>.*?'               # 코드확인
        r'<span[^>]*>\s*(1Q|2Q|3Q|4Q|本決算|中間|通期|本)\s*</span>.*?'  # 결산종류
        r'(\d{4}/\d{2}/\d{2})',                       # 발표일
        html, re.DOTALL
    )

    print(f"  카드 파싱: {len(cards)}건")

    for code, name, ktype, date_raw in cards:
        # 済(완료) 종목도 포함 — 발표일 기준으로 필터는 VPS에서
        try:
            dt = datetime.strptime(date_raw, "%Y/%m/%d")
            kessan_date = dt.strftime("%Y-%m-%d")
        except:
            continue

        # 과거 데이터 스킵 (오늘 이전)
        if dt.date() < now.date():
            continue

        key = f"{code}_{kessan_date}"
        if key in seen:
            continue
        seen.add(key)

        items.append({
            "code":          code[:4],
            "name":          name.strip()[:20],
            "market":        "",
            "fiscal_period": ktype.strip(),
            "kessan_date":   kessan_date,
            "kessan_time":   "",
            "source":        "kabuyoho",
        })

    return items


def fetch_nikkei225jp() -> list:
    url = "https://nikkei225jp.com/schedule/"
    h = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120",
         "Accept-Language": "ja,en;q=0.9"}
    try:
        res = requests.get(url, headers=h, timeout=15)
        res.raise_for_status()
        html = res.text
    except:
        return []
    now = datetime.now(JST)
    m = re.search(r'決算予定[^\n]*日経225(.*?)(?=決算予定[^\n]*(?:米|S&P)|市場休日)', html, re.DOTALL)
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
            items.append({"code": code[:4], "name": name[:20], "market": "日経225",
                          "fiscal_period": "", "kessan_date": current_date,
                          "kessan_time": "", "source": "nikkei225jp"})
    return items


def push_to_vps(items):
    r = requests.post(f"{VPS_BASE_URL}/push/kessan",
                      json={"items": items, "secret": VPS_PUSH_SECRET}, timeout=30)
    if r.status_code == 200:
        j = r.json()
        print(f"  ✅ push: {j.get('saved',0)}건 저장 / {j.get('total',0)}건")
    else:
        print(f"  ❌ push 실패: {r.status_code}")
        sys.exit(1)


def main():
    now = datetime.now(JST)
    print(f"=== 결산예정 수집 ({now.strftime('%Y-%m-%d %H:%M JST')}) ===")

    print("\n[소스1] kabuyoho.jp 수집 중...")
    items = fetch_kabuyoho()
    print(f"  소계: {len(items)}건")

    if items:
        for it in items[:5]:
            print(f"  {it['kessan_date']} [{it['code']}] {it['name']} {it['fiscal_period']}")
        if len(items) > 5:
            print(f"  ... 외 {len(items)-5}건")
    else:
        print("\n[소스2] nikkei225jp fallback...")
        items = fetch_nikkei225jp()
        print(f"  소계: {len(items)}건")

    if not items:
        print("  ⚠️ 데이터 없음")
        sys.exit(0)

    push_to_vps(items)
    print("=== 완료 ===")

if __name__ == "__main__":
    main()
