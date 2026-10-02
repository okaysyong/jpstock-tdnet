"""
fetch_kessan.py (kabuyoho PC버전 v2)
"""
import os, sys, re, requests
from datetime import datetime, timedelta, timezone
from collector_parsing import STOCK_CODE_PATTERN

JST = timezone(timedelta(hours=9))
VPS_BASE_URL    = os.environ.get("VPS_BASE_URL", "https://jpstocklive.com")
VPS_PUSH_SECRET = os.environ.get("VPS_PUSH_SECRET", "")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "ja,en;q=0.9",
    "Referer": "https://kabuyoho.jp/",
}

def fetch_kabuyoho_date(date_str: str) -> list:
    yyyymmdd = date_str.replace("-", "")
    yyyymm   = date_str[:7].replace("-", "")
    url = f"https://kabuyoho.jp/calender?lst={yyyymmdd}&publ=off&ym={yyyymm}&sett=4"

    try:
        res = requests.get(url, headers=HEADERS, timeout=15)
        res.raise_for_status()
        html = res.text
    except requests.RequestException:
        raise RuntimeError('Earnings calendar download failed') from None

    # stocklist 섹션만 추출
    m = re.search(r'id="stocklist">(.*?)(?=</section>|<section)', html, re.DOTALL)
    if not m:
        raise RuntimeError('Earnings calendar page format changed')
    section = m.group(1)

    items = []
    seen = set()

    # 패턴: bcode=XXXX" title="종목명">
    # 결산종류: 별도 <td> or <span>에 1Q/2Q/3Q/本決算/中間
    # bcode와 결산종류를 카드 단위로 묶어서 파싱
    card_blocks = re.split(r'(?=bcode=' + STOCK_CODE_PATTERN + r')', section)

    for block in card_blocks:
        # 종목코드
        cm = re.search(r'bcode=(' + STOCK_CODE_PATTERN + r')', block)
        if not cm:
            continue
        code = cm.group(1)

        # 종목명: title 속성 또는 <p> 태그
        nm = re.search(r'title="([^"]{2,20})"', block)
        if not nm:
            nm = re.search(r'<p>([^<]{2,20})</p>', block)
        name = nm.group(1).strip() if nm else ""
        if not name:
            continue

        # 결산종류
        km = re.search(r'(1Q|2Q|3Q|4Q|本決算|中間|通期)', block)
        ktype = km.group(1) if km else ""

        key = f"{code}_{date_str}"
        if key in seen:
            continue
        seen.add(key)

        items.append({
            "code":          code[:4],
            "name":          name[:20],
            "market":        "",
            "fiscal_period": ktype,
            "kessan_date":   date_str,
            "kessan_time":   "",
            "source":        "kabuyoho",
        })

    return items

def push_to_vps(items):
    from collector_common import push_json
    return push_json(VPS_BASE_URL,"/push/kessan",{"items":items})

def main():
    now = datetime.now(JST)
    print(f"=== 결산예정 수집 ({now.strftime('%Y-%m-%d %H:%M JST')}) ===")

    all_items = []
    seen_keys = set()

    for delta in range(20):
        target = now + timedelta(days=delta)
        if target.weekday() >= 5:
            continue
        date_str = target.strftime("%Y-%m-%d")
        items = fetch_kabuyoho_date(date_str)
        new = 0
        for it in items:
            k = f"{it['code']}_{it['kessan_date']}"
            if k not in seen_keys:
                seen_keys.add(k)
                all_items.append(it)
                new += 1
        print(f"  {date_str}: {new}건")

    print(f"\n총 {len(all_items)}건")
    if not all_items:
        print("  ⚠️ 데이터 없음")
        sys.exit(0)

    for it in all_items[:5]:
        print(f"  {it['kessan_date']} [{it['code']}] {it['name']} {it['fiscal_period']}")
    if len(all_items) > 5:
        print(f"  ... 외 {len(all_items)-5}건")

    push_to_vps(all_items)
    print("=== 완료 ===")

if __name__ == "__main__":
    main()
