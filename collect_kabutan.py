"""
collect_kabutan.py
카부탄 속보 뉴스 + 애널리스트 리포트 수집 → VPS push
GitHub Actions에서 5분마다 실행
"""
import os, re, time, requests, hashlib
from datetime import datetime
from zoneinfo import ZoneInfo

JST = ZoneInfo("Asia/Tokyo")
VPS_API_URL = os.environ.get("VPS_NEWS_API_URL", "")
VPS_TOKEN   = os.environ.get("VPS_TOKEN", "")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.9",
    "Accept-Language": "ja,en-US;q=0.9",
    "Referer": "https://kabutan.jp/",
}

# ── 카부탄 수집 URL ────────────────────────────────
KABUTAN_URLS = {
    # 속보 뉴스 (종목별 재료)
    "news_market":  "https://kabutan.jp/news/marketnews/",
    # 레이팅/목표주가 변경
    "rating":       "https://kabutan.jp/warning/?mode=6_3&market=1",
    # 스톱하이
    "stop_high":    "https://kabutan.jp/warning/?mode=1_2&market=1",
    # 스톱로
    "stop_low":     "https://kabutan.jp/warning/?mode=1_3&market=1",
    # 연속 상승
    "rise_cont":    "https://kabutan.jp/warning/?mode=1_4&market=1",
}

# 중요도 키워드
HIGH_KW = [
    "急騰", "急落", "ストップ高", "ストップ安", "上方修正", "下方修正",
    "増配", "減配", "自己株", "TOB", "合併", "子会社", "格上げ", "格下げ",
    "目標株価引き上げ", "目標株価引き下げ", "大幅高", "大幅安",
    "S高", "S安", "新高値", "年初来高値",
]
MED_KW = [
    "続伸", "続落", "反発", "反落", "堅調", "軟調",
    "業績", "黒字", "赤字", "増収", "増益", "減収", "減益",
    "受注", "契約", "提携", "新製品",
]

def classify_importance(title: str) -> int:
    if any(kw in title for kw in HIGH_KW): return 3
    if any(kw in title for kw in MED_KW): return 2
    return 1

def fetch_news_market() -> list:
    """카부탄 마켓 속보 뉴스 수집"""
    try:
        r = requests.get(KABUTAN_URLS["news_market"], headers=HEADERS, timeout=15)
        if r.status_code != 200:
            print(f"  [카부탄뉴스] HTTP {r.status_code}")
            return []
        html = r.text
        items = []
        now_str = datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S")
        today   = datetime.now(JST).strftime("%Y-%m-%d")

        # 뉴스 파싱: 종목코드 + 제목
        # 패턴: <a href="/stock/get_stock_info.php?code=XXXX">종목명</a>..제목
        news_rows = re.findall(
            r'<dt[^>]*>(\d{2}:\d{2})</dt>.*?'
            r'(?:code=(\d{4}[A-Z]?).*?)?'
            r'<a[^>]+href="/news/[^"]*"[^>]*>([^<]{5,80})</a>',
            html, re.DOTALL
        )

        # 대안 파싱
        if not news_rows:
            news_rows = re.findall(
                r'<span[^>]*class="[^"]*time[^"]*"[^>]*>(\d{2}:\d{2})</span>.*?'
                r'code=(\d{4}[A-Z]?).*?'
                r'>([^<]{5,80})</a>',
                html, re.DOTALL
            )

        # tbody 기반 파싱
        trs = re.findall(r'<tr[^>]*>(.*?)</tr>', html, re.DOTALL)
        for tr in trs[:50]:
            time_m = re.search(r'(\d{2}:\d{2})', tr)
            code_m = re.search(r'code=(\d{4}[A-Z]?)', tr)
            title_m = re.search(r'<a[^>]+href="/news/[^"]*"[^>]*>([^<]{5,80})</a>', tr)
            if not title_m:
                continue
            t     = time_m.group(1) if time_m else "00:00"
            code  = code_m.group(1) if code_m else ""
            title = title_m.group(1).strip()
            imp   = classify_importance(title)
            if imp < 2:
                continue  # 중요도 낮은 것 제외
            uid = hashlib.md5(f"kab_{today}_{code}_{title}".encode()).hexdigest()[:12]
            items.append({
                "uid":          uid,
                "title":        f"[{code}] {title}" if code else title,
                "summary":      "",
                "url":          f"https://kabutan.jp/news/marketnews/",
                "source":       "kabutan_news",
                "published_at": f"{today} {t}:00",
                "stocks":       f'["{code}"]' if code else "[]",
                "importance":   imp,
            })

        # 중복 제거
        seen = set()
        result = []
        for it in items:
            if it["uid"] not in seen:
                seen.add(it["uid"])
                result.append(it)

        print(f"  [카부탄뉴스] {len(result)}건 (중요도2+)")
        return result
    except Exception as e:
        print(f"  [카부탄뉴스] 오류: {e}")
        return []


def fetch_rating() -> list:
    """애널리스트 레이팅/목표주가 변경 수집"""
    try:
        r = requests.get(KABUTAN_URLS["rating"], headers=HEADERS, timeout=15)
        if r.status_code != 200:
            return []
        html = r.text
        items = []
        now_str = datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S")
        today   = datetime.now(JST).strftime("%Y-%m-%d")

        trs = re.findall(r'<tr[^>]*>(.*?)</tr>', html, re.DOTALL)
        for tr in trs[:30]:
            code_m  = re.search(r'code=(\d{4}[A-Z]?)', tr)
            name_m  = re.search(r'<a[^>]+stock[^>]+>([^<]+)</a>', tr)
            # 레이팅 내용
            tds = re.findall(r'<td[^>]*>([^<]{2,40})</td>', tr)
            if not code_m or len(tds) < 3:
                continue
            code  = code_m.group(1)
            name  = name_m.group(1).strip() if name_m else ""
            # 레이팅 변경 내용 조합
            rating_info = " ".join(td.strip() for td in tds[1:4] if td.strip())
            if not rating_info:
                continue
            title = f"{name} {rating_info}"
            uid = hashlib.md5(f"kab_rating_{today}_{code}_{rating_info}".encode()).hexdigest()[:12]
            items.append({
                "uid":          uid,
                "title":        f"[{code}] {title}",
                "summary":      "",
                "url":          KABUTAN_URLS["rating"],
                "source":       "kabutan_rating",
                "published_at": now_str,
                "stocks":       f'["{code}"]',
                "importance":   3,
            })

        print(f"  [레이팅] {len(items)}건")
        return items
    except Exception as e:
        print(f"  [레이팅] 오류: {e}")
        return []


def fetch_stop_stocks() -> list:
    """스톱하이/스톱로 종목 수집"""
    items = []
    for category, url in [("stop_high", KABUTAN_URLS["stop_high"]),
                           ("stop_low",  KABUTAN_URLS["stop_low"])]:
        try:
            r = requests.get(url, headers=HEADERS, timeout=15)
            if r.status_code != 200:
                continue
            html = r.text
            today = datetime.now(JST).strftime("%Y-%m-%d")
            now_str = datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S")
            label = "ストップ高" if "high" in category else "ストップ安"

            trs = re.findall(r'<tr[^>]*>(.*?)</tr>', html, re.DOTALL)
            for tr in trs[:20]:
                code_m = re.search(r'code=(\d{4}[A-Z]?)', tr)
                name_m = re.search(r'<a[^>]+stock[^>]+>([^<]+)</a>', tr)
                if not code_m:
                    continue
                code  = code_m.group(1)
                name  = name_m.group(1).strip() if name_m else code
                title = f"{name} {label}"
                uid = hashlib.md5(f"kab_{category}_{today}_{code}".encode()).hexdigest()[:12]
                items.append({
                    "uid":          uid,
                    "title":        f"[{code}] {title}",
                    "summary":      "",
                    "url":          url,
                    "source":       f"kabutan_{category}",
                    "published_at": now_str,
                    "stocks":       f'["{code}"]',
                    "importance":   3,
                })
            print(f"  [{label}] {len([i for i in items if category in i['source']])}건")
            time.sleep(1)
        except Exception as e:
            print(f"  [{category}] 오류: {e}")
    return items


def push_news_to_vps(items: list) -> None:
    if not items or not VPS_API_URL:
        return
    try:
        headers = {"Content-Type": "application/json"}
        if VPS_TOKEN:
            headers["X-Push-Token"] = VPS_TOKEN
        res = requests.post(
            f"{VPS_API_URL}/push/news",
            json={"items": items},
            headers=headers,
            timeout=20
        )
        data = res.json()
        print(f"  VPS push: {data.get('saved',0)}/{len(items)}건")
    except Exception as e:
        print(f"  VPS push 오류: {e}")


def main():
    now = datetime.now(JST)
    print(f"=== 카부탄 속보 수집: {now.strftime('%Y-%m-%d %H:%M:%S')} JST ===")

    all_items = []

    # 1. 마켓 속보 뉴스
    news = fetch_news_market()
    all_items.extend(news)
    time.sleep(2)

    # 2. 애널리스트 레이팅
    rating = fetch_rating()
    all_items.extend(rating)
    time.sleep(2)

    # 3. 스톱하이/스톱로
    stops = fetch_stop_stocks()
    all_items.extend(stops)

    print(f"\n총 {len(all_items)}건 수집")
    push_news_to_vps(all_items)
    print("완료")


if __name__ == "__main__":
    main()
