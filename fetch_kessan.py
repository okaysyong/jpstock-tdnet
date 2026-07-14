import os, sys, re, requests
from datetime import datetime, timedelta, timezone

JST = timezone(timedelta(hours=9))
VPS_BASE_URL    = os.environ.get("VPS_BASE_URL", "https://jpstocklive.com")
VPS_PUSH_SECRET = os.environ.get("VPS_PUSH_SECRET", "")

def fetch_nikkei225jp():
    url = "https://nikkei225jp.com/schedule/"
    h = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120", "Accept-Language": "ja,en;q=0.9"}
    res = requests.get(url, headers=h, timeout=15)
    html = res.text
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

def main():
    now = datetime.now(JST)
    print(f"=== 결산예정 수집 ({now.strftime('%Y-%m-%d %H:%M JST')}) ===")

    # kabuyoho HTML 저장 후 구조 파악
    print("\n[kabuyoho 디버그]")
    HEADERS_SP = {"User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1", "Accept-Language": "ja,en;q=0.9"}
    res = requests.get("https://kabuyoho.jp/sp/calender", headers=HEADERS_SP, timeout=15)
    html = res.text
    print(f"HTTP {res.status_code}, {len(html)}자")

    # 날짜 패턴
    for pat in [r'\d{1,2}月\d{1,2}日', r'\d{4}/\d{2}/\d{2}', r'\d{2}/\d{2}\(']:
        found = re.findall(pat, html)
        if found:
            print(f"날짜패턴 '{pat}': {found[:8]}")

    # 종목코드
    codes = re.findall(r'[>\s/](\d{4})[A-Z]?[<\s"\']', html)
    print(f"종목코드 샘플: {list(dict.fromkeys(codes))[:10]}")

    # 결산종류
    for kw in ['1Q','2Q','3Q','本決算','中間','通期','四半期','発表日']:
        idx = html.find(kw)
        if idx >= 0:
            print(f"[{kw}]@{idx}: {repr(html[max(0,idx-60):idx+60])}")

    # HTML 앞부분
    print("\n--- HTML 1000~2000자 ---")
    print(repr(html[1000:2000]))

    # nikkei225jp fallback
    print("\n[nikkei225jp fallback]")
    items = fetch_nikkei225jp()
    print(f"수집: {len(items)}건")
    if items:
        url = f"{VPS_BASE_URL}/push/kessan"
        r = requests.post(url, json={"items": items, "secret": VPS_PUSH_SECRET}, timeout=30)
        j = r.json()
        print(f"✅ push: {j.get('saved',0)}건")
    print("=== 완료 ===")

if __name__ == "__main__":
    main()
