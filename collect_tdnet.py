"""
collect_tdnet.py
카부탄에서 결산/공시 데이터 수집 → VPS push
GitHub Actions에서 10분마다 실행
"""
import os, re, time, json, hashlib, requests
from datetime import datetime
from zoneinfo import ZoneInfo

JST = ZoneInfo("Asia/Tokyo")
VPS_API_URL = os.environ.get("VPS_NEWS_API_URL", "")
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ja,en-US;q=0.9",
}

KABUTAN_URLS = {
    "today_market": "https://kabutan.jp/warning/?mode=2_1&market=1&capitalization=0",
    "today_after":  "https://kabutan.jp/warning/?mode=2_2&market=1&capitalization=0",
    "tomorrow":     "https://kabutan.jp/warning/?mode=2_3&market=1&capitalization=0",
    "golden":       "https://kabutan.jp/warning/?mode=3_1&market=1",
    "dead":         "https://kabutan.jp/warning/?mode=3_2&market=1",
}

RANK3_KW = ["決算短信", "業績予想", "業績修正", "TOB", "合併", "上場廃止", "民事再生", "配当予想修正"]
RANK2_KW = ["業務提携", "資本提携", "増資", "株式分割", "代表取締役", "社長交代"]


def fetch_kabutan(category: str, url: str) -> list:
    """카부탄 페이지에서 종목 정보 수집"""
    try:
        res = requests.get(url, headers=HEADERS, timeout=15)
        res.encoding = "utf-8"
        html = res.text

        stocks = []
        # 종목 테이블 파싱
        rows = re.findall(
            r'<td[^>]*class="[^"]*stock_code[^"]*"[^>]*>.*?(\d{4}[A-Z]?)</td>.*?'
            r'<td[^>]*class="[^"]*stock_name[^"]*"[^>]*>.*?<a[^>]*>([^<]+)</a>',
            html, re.DOTALL
        )
        if not rows:
            # 대안 파싱
            rows = re.findall(
                r'<a href="/stock/[^"]*">.*?(\d{4})</a>.*?<a href="/stock/[^"]*">([^<]+)</a>',
                html, re.DOTALL
            )

        # 간단한 파싱 - 코드와 이름
        code_names = re.findall(r'stock\?code=(\d{4}[A-Z]?).*?class="[^"]*name[^"]*"[^>]*>([^<]+)<', html, re.DOTALL)
        if not code_names:
            # tbody 내 td 파싱
            tbody = re.search(r'<tbody>(.*?)</tbody>', html, re.DOTALL)
            if tbody:
                trs = re.findall(r'<tr[^>]*>(.*?)</tr>', tbody.group(1), re.DOTALL)
                for tr in trs[:20]:
                    code_m = re.search(r'(\d{4}[A-Z]?)', tr)
                    name_m = re.search(r'<a[^>]+>([^\d<][^<]{2,})</a>', tr)
                    if code_m and name_m:
                        code_names.append((code_m.group(1), name_m.group(1).strip()))

        now_str = datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S")
        today   = datetime.now(JST).strftime("%Y%m%d")

        seen = set()
        for code, name in code_names[:20]:
            name = name.strip()
            if not code or not name or code in seen:
                continue
            seen.add(code)

            title = f"{name} 決算発表"
            disc_id = f"kabutan_{code}_{category}_{today}"

            rank = 1
            for kw in RANK3_KW:
                if kw in title:
                    rank = 3
                    break
            if rank < 3:
                for kw in RANK2_KW:
                    if kw in title:
                        rank = 2
                        break
            if rank < 2 and category == "today_market":
                rank = 2

            stocks.append({
                "disclosure_id": disc_id,
                "stock_code":    code,
                "company_name":  name,
                "title":         title,
                "disclosed_at":  now_str,
                "rank":          rank,
                "pdf_url":       "",
            })

        print(f"  [{category}] {len(stocks)}종목")
        return stocks

    except Exception as e:
        print(f"  [{category}] 오류: {e}")
        return []


def push_to_vps(items: list) -> None:
    """VPS에 공시 데이터 push"""
    if not items:
        return
    try:
        res = requests.post(
            f"{VPS_API_URL}/push/tdnet",
            json={"items": items},
            timeout=15
        )
        data = res.json()
        print(f"  VPS push: {data.get('saved',0)}/{len(items)}건 저장 (news_feed: {data.get('news_saved',0)}건)")
    except Exception as e:
        print(f"  VPS push 오류: {e}")


def main():
    now_jst = datetime.now(JST)
    print(f"=== TDnet 수집 시작: {now_jst.strftime('%Y-%m-%d %H:%M:%S')} JST ===")

    all_items = []
    for category, url in KABUTAN_URLS.items():
        items = fetch_kabutan(category, url)
        all_items.extend(items)
        time.sleep(2)  # 과도한 요청 방지

    print(f"\n총 {len(all_items)}건 수집")
    push_to_vps(all_items)
    print("완료")


if __name__ == "__main__":
    main()
