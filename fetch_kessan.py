"""
fetch_kessan.py (kabuyoho PC버전 날짜별)
https://kabuyoho.jp/calender?lst=YYYYMMDD&publ=on&ym=YYYYMM&sett=4
"""
import os, sys, re, requests
from datetime import datetime, timedelta, timezone

JST = timezone(timedelta(hours=9))
VPS_BASE_URL    = os.environ.get("VPS_BASE_URL", "https://jpstocklive.com")
VPS_PUSH_SECRET = os.environ.get("VPS_PUSH_SECRET", "")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "ja,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Referer": "https://kabuyoho.jp/",
}

def fetch_kabuyoho_date(date_str: str) -> list:
    """
    date_str: YYYY-MM-DD
    URL: https://kabuyoho.jp/calender?lst=YYYYMMDD&publ=on&ym=YYYYMM&sett=4
    """
    yyyymmdd = date_str.replace("-", "")
    yyyymm   = date_str[:7].replace("-", "")
    url = f"https://kabuyoho.jp/calender?lst={yyyymmdd}&publ=on&ym={yyyymm}&sett=4"

    try:
        res = requests.get(url, headers=HEADERS, timeout=15)
        print(f"  {date_str}: HTTP {res.status_code}, {len(res.text)}자")
        if res.status_code != 200:
            return []
        html = res.text
    except Exception as e:
        print(f"  {date_str}: 오류 {e}")
        return []

    items = []
    seen = set()

    # 디버그: 키워드 확인
    for kw in ['1Q','2Q','3Q','本決算','中間','stocklist','bcode=']:
        idx = html.find(kw)
        if idx >= 0:
            print(f"  [{kw}]@{idx}: {repr(html[idx:idx+80])}")

    # 파싱 시도
    # PC 버전: /reportTop?bcode=XXXX 또는 /stock/XXXX
    cards = re.findall(
        r'bcode=(\d{4})[^>]*>([^<]{2,20})</a>'
        r'.*?(1Q|2Q|3Q|4Q|本決算|中間|通期)',
        html, re.DOTALL
    )
    print(f"  파싱 카드: {len(cards)}건")

    for code, name, ktype in cards:
        key = f"{code}_{date_str}"
        if key in seen:
            continue
        seen.add(key)
        items.append({
            "code":          code[:4],
            "name":          name.strip()[:20],
            "market":        "",
            "fiscal_period": ktype.strip(),
            "kessan_date":   date_str,
            "kessan_time":   "",
            "source":        "kabuyoho",
        })

    return items

def push_to_vps(items):
    r = requests.post(f"{VPS_BASE_URL}/push/kessan",
                      json={"items": items, "secret": VPS_PUSH_SECRET}, timeout=30)
    if r.status_code == 200:
        j = r.json()
        print(f"  ✅ push: {j.get('saved',0)}건 저장")
    else:
        print(f"  ❌ 실패: {r.status_code}")
        sys.exit(1)

def main():
    now = datetime.now(JST)
    print(f"=== 결산예정 수집 ({now.strftime('%Y-%m-%d %H:%M JST')}) ===")

    all_items = []
    seen_keys = set()

    # 오늘부터 14영업일치
    for delta in range(20):
        target = now + timedelta(days=delta)
        if target.weekday() >= 5:
            continue
        date_str = target.strftime("%Y-%m-%d")
        items = fetch_kabuyoho_date(date_str)
        for it in items:
            k = f"{it['code']}_{it['kessan_date']}"
            if k not in seen_keys:
                seen_keys.add(k)
                all_items.append(it)

    print(f"\n총 {len(all_items)}건")
    if all_items:
        for it in all_items[:5]:
            print(f"  {it['kessan_date']} [{it['code']}] {it['name']} {it['fiscal_period']}")
        push_to_vps(all_items)
    print("=== 완료 ===")

if __name__ == "__main__":
    main()
