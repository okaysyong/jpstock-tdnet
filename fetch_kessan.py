"""
fetch_kessan.py (최종 v2)
- nikkei225jp.com/schedule/ : 2주치 日経225 결산예정
- 매일 06:00 JST GitHub Actions 실행
"""
import os, sys, re, requests
from datetime import datetime, timedelta, timezone

JST = timezone(timedelta(hours=9))
VPS_BASE_URL    = os.environ.get("VPS_BASE_URL", "https://jpstocklive.com")
VPS_PUSH_SECRET = os.environ.get("VPS_PUSH_SECRET", "")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120",
    "Accept-Language": "ja,en;q=0.9",
}

def fetch_nikkei225jp() -> list:
    try:
        res = requests.get("https://nikkei225jp.com/schedule/", headers=HEADERS, timeout=15)
        res.raise_for_status()
        html = res.text
    except Exception as e:
        print(f"  ❌ 취득 실패: {e}")
        return []

    now = datetime.now(JST)
    m = re.search(r'決算予定[^\n]*日経225(.*?)(?=決算予定[^\n]*(?:米|S&P)|市場休日)', html, re.DOTALL)
    if not m:
        print("  ⚠️ 日経225 섹션 없음")
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
    print("  소스: nikkei225jp.com (日経225 2주치)")

    items = fetch_nikkei225jp()
    print(f"  수집: {len(items)}건")

    if not items:
        print("  ⚠️ 데이터 없음")
        sys.exit(0)

    for it in items[:5]:
        print(f"    {it['kessan_date']} [{it['code']}] {it['name']}")
    if len(items) > 5:
        print(f"    ... 외 {len(items)-5}건")

    push_to_vps(items)
    print("=== 완료 ===")

if __name__ == "__main__":
    main()
