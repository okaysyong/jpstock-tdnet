"""
fetch_kessan.py (v3 - debug)
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

def fetch_kessan_nikkei225jp() -> list:
    url = "https://nikkei225jp.com/schedule/"
    try:
        res = requests.get(url, headers=HEADERS, timeout=15)
        res.raise_for_status()
        html = res.text
    except Exception as e:
        print(f"  ❌ 취득 실패: {e}")
        return []

    print(f"  HTML 크기: {len(html)}자")

    # ── 디버그: 결산 관련 키워드 위치 출력 ──
    for kw in ["決算予定", "kessan", "ベイカレント", "yahoo.co.jp/quote", "6532"]:
        idx = html.find(kw)
        if idx >= 0:
            print(f"  [{kw}] @ {idx}: {repr(html[idx:idx+120])}")

    items = []
    now = datetime.now(JST)
    current_year = now.year

    # ── 방법1: 기존 섹션 추출 ──
    m = re.search(
        r'決算予定[^\n]*日経225(.*?)(?=決算予定[^\n]*(?:米|S&P)|市場休日)',
        html, re.DOTALL
    )
    if m:
        section = m.group(1)
        print(f"  섹션 발견 (방법1): {len(section)}자")
    else:
        # ── 방법2: yahoo.co.jp/quote 링크 전체에서 날짜+종목 추출 ──
        print("  방법2 시도: 전체 HTML에서 날짜+종목 파싱")
        section = html

    # 날짜 블록 파싱
    date_blocks = re.split(r'(\d{2}/\d{2}\([月火水木金土日]\))', section)
    print(f"  날짜 블록 수: {len(date_blocks)}")

    # 날짜 블록 샘플 출력
    for i, blk in enumerate(date_blocks[:10]):
        if re.match(r'\d{2}/\d{2}', blk.strip()):
            print(f"  블록[{i}]: {repr(blk.strip()[:80])}")

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
    except Exception as e:
        print(f"  ❌ VPS push 오류: {e}")

def main():
    now = datetime.now(JST)
    print(f"=== 결산예정 수집 시작 ({now.strftime('%Y-%m-%d %H:%M JST')}) ===")

    items = fetch_kessan_nikkei225jp()
    print(f"  수집: {len(items)}건")

    if items:
        for it in items[:5]:
            print(f"    {it['kessan_date']} [{it['code']}] {it['name']}")
        if len(items) > 5:
            print(f"    ... 외 {len(items)-5}건")
        push_to_vps(items)
    else:
        print("  ⚠️ 데이터 없음 — 디버그 정보 확인 필요")

    print("=== 완료 ===")

if __name__ == "__main__":
    main()
