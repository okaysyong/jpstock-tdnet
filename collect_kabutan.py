"""
collect_kabutan.py
카부탄/민카부 속보 뉴스 + 애널리스트 리포트 수집 → VPS push
GitHub Actions에서 5분마다 실행
"""
import os, re, time, requests, hashlib
from datetime import datetime
from zoneinfo import ZoneInfo

JST = ZoneInfo("Asia/Tokyo")
VPS_API_URL = os.environ.get("VPS_NEWS_API_URL", "")
VPS_TOKEN   = os.environ.get("VPS_TOKEN", "")

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "ja-JP,ja;q=0.9,en-US;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Cache-Control": "max-age=0",
})

HIGH_KW = [
    "急騰","急落","ストップ高","ストップ安","S高","S安",
    "上方修正","下方修正","増配","減配","自己株","TOB",
    "合併","子会社","格上げ","格下げ","目標株価引き上げ",
    "目標株価引き下げ","大幅高","大幅安","新高値","年初来高値",
]
MED_KW = [
    "続伸","続落","反発","反落","堅調","軟調",
    "業績","黒字","赤字","増収","増益","減収","減益",
    "受注","契約","提携","新製品",
]

def classify_importance(title: str) -> int:
    if any(kw in title for kw in HIGH_KW): return 3
    if any(kw in title for kw in MED_KW): return 2
    return 1


def fetch_news_market() -> list:
    """카부탄 마켓 속보"""
    try:
        r = SESSION.get("https://kabutan.jp/news/marketnews/", timeout=15)
        if r.status_code != 200:
            print(f"  [카부탄] HTTP {r.status_code}")
            return []
        html = r.text
        today   = datetime.now(JST).strftime("%Y-%m-%d")
        now_str = datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S")
        items = []
        seen  = set()
        trs = re.findall(r'<tr[^>]*>(.*?)</tr>', html, re.DOTALL)
        for tr in trs[:60]:
            time_m  = re.search(r'(\d{2}:\d{2})', tr)
            code_m  = re.search(r'code=(\d{4}[A-Z]?)', tr)
            title_m = re.search(r'<a[^>]+href="/news/[^"]*"[^>]*>([^<]{5,80})</a>', tr)
            if not title_m:
                continue
            t     = time_m.group(1) if time_m else "00:00"
            code  = code_m.group(1) if code_m else ""
            title = title_m.group(1).strip()
            imp   = classify_importance(title)
            if imp < 2:
                continue
            uid = hashlib.md5(f"kab_{today}_{code}_{title}".encode()).hexdigest()[:12]
            if uid in seen: continue
            seen.add(uid)
            items.append({
                "uid":          uid,
                "title":        f"[{code}] {title}" if code else title,
                "summary":      "",
                "url":          "https://kabutan.jp/news/marketnews/",
                "source":       "kabutan_news",
                "published_at": f"{today} {t}:00",
                "stocks":       f'["{code}"]' if code else "[]",
                "importance":   imp,
            })
        print(f"  [카부탄] {len(items)}건")
        return items
    except Exception as e:
        print(f"  [카부탄] 오류: {e}")
        return []


def fetch_minkabu_news() -> list:
    """민카부 속보 (카부탄 폴백)"""
    try:
        r = SESSION.get("https://minkabu.jp/news/stock", timeout=15)
        if r.status_code != 200:
            print(f"  [민카부] HTTP {r.status_code}")
            return []
        html = r.text
        today   = datetime.now(JST).strftime("%Y-%m-%d")
        now_str = datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S")
        items = []
        seen  = set()
        # 종목코드 + 뉴스 제목 파싱
        code_rows = re.findall(
            r'/stock/(\d{4}[A-Z]?)[^"]*".*?'
            r'<a[^>]+href="/news/\d+"[^>]*>([^<]{5,100})</a>',
            html, re.DOTALL
        )
        for code, title in code_rows[:40]:
            title = title.strip()
            imp   = classify_importance(title)
            if imp < 2: continue
            uid = hashlib.md5(f"minka_{today}_{code}_{title}".encode()).hexdigest()[:12]
            if uid in seen: continue
            seen.add(uid)
            items.append({
                "uid":          uid,
                "title":        f"[{code}] {title}",
                "summary":      "",
                "url":          f"https://minkabu.jp/stock/{code}/news",
                "source":       "minkabu_news",
                "published_at": now_str,
                "stocks":       f'["{code}"]',
                "importance":   imp,
            })
        print(f"  [민카부] {len(items)}건")
        return items
    except Exception as e:
        print(f"  [민카부] 오류: {e}")
        return []


def fetch_rating() -> list:
    """애널리스트 레이팅/목표주가 변경"""
    try:
        r = SESSION.get("https://kabutan.jp/warning/?mode=6_3&market=1", timeout=15)
        if r.status_code != 200:
            return []
        html    = r.text
        today   = datetime.now(JST).strftime("%Y-%m-%d")
        now_str = datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S")
        items   = []
        seen    = set()
        trs = re.findall(r'<tr[^>]*>(.*?)</tr>', html, re.DOTALL)
        for tr in trs[:30]:
            code_m = re.search(r'code=(\d{4}[A-Z]?)', tr)
            name_m = re.search(r'<a[^>]+stock[^>]+>([^<]+)</a>', tr)
            tds    = re.findall(r'<td[^>]*>([^<]{2,40})</td>', tr)
            if not code_m or len(tds) < 3: continue
            code   = code_m.group(1)
            name   = name_m.group(1).strip() if name_m else ""
            info   = " ".join(td.strip() for td in tds[1:4] if td.strip())
            if not info: continue
            title = f"{name} {info}"
            uid = hashlib.md5(f"kab_rating_{today}_{code}_{info}".encode()).hexdigest()[:12]
            if uid in seen: continue
            seen.add(uid)
            items.append({
                "uid":          uid,
                "title":        f"[{code}] {title}",
                "summary":      "",
                "url":          "https://kabutan.jp/warning/?mode=6_3",
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
    """스톱하이/스톱로"""
    items = []
    for label, url in [("ストップ高", "https://kabutan.jp/warning/?mode=1_2&market=1"),
                       ("ストップ安", "https://kabutan.jp/warning/?mode=1_3&market=1")]:
        try:
            r = SESSION.get(url, timeout=15)
            if r.status_code != 200: continue
            html    = r.text
            today   = datetime.now(JST).strftime("%Y-%m-%d")
            now_str = datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S")
            trs = re.findall(r'<tr[^>]*>(.*?)</tr>', html, re.DOTALL)
            cnt = 0
            for tr in trs[:20]:
                code_m = re.search(r'code=(\d{4}[A-Z]?)', tr)
                name_m = re.search(r'<a[^>]+stock[^>]+>([^<]+)</a>', tr)
                if not code_m: continue
                code  = code_m.group(1)
                name  = name_m.group(1).strip() if name_m else code
                title = f"{name} {label}"
                uid = hashlib.md5(f"kab_stop_{today}_{code}_{label}".encode()).hexdigest()[:12]
                items.append({
                    "uid":          uid,
                    "title":        f"[{code}] {title}",
                    "summary":      "",
                    "url":          url,
                    "source":       "kabutan_stop",
                    "published_at": now_str,
                    "stocks":       f'["{code}"]',
                    "importance":   3,
                })
                cnt += 1
            print(f"  [{label}] {cnt}건")
            time.sleep(1)
        except Exception as e:
            print(f"  [{label}] 오류: {e}")
    return items


def push_to_vps(items: list) -> None:
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
        print(f"  VPS: {data.get('saved',0)}/{len(items)}건 저장")
    except Exception as e:
        print(f"  VPS 오류: {e}")


def main():
    now = datetime.now(JST)
    print(f"=== 카부탄 속보 수집: {now.strftime('%Y-%m-%d %H:%M:%S')} JST ===")
    all_items = []

    # 1. 속보 뉴스 (카부탄 → 민카부 폴백)
    news = fetch_news_market()
    if not news:
        print("  카부탄 실패 → 민카부 시도")
        news = fetch_minkabu_news()
    all_items.extend(news)
    time.sleep(2)

    # 2. 레이팅 변경
    all_items.extend(fetch_rating())
    time.sleep(2)

    # 3. 스톱하이/스톱로
    all_items.extend(fetch_stop_stocks())

    print(f"\n총 {len(all_items)}건 수집")
    push_to_vps(all_items)
    print("완료")


if __name__ == "__main__":
    main()
