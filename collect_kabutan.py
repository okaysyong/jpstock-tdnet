"""
collect_kabutan.py
카부탄/민카부 속보 뉴스 + 애널리스트 리포트 + 업적수정/결산/M&A 수집 → VPS push
GitHub Actions에서 5분마다 실행

v2 변경사항:
- 업적수정/결산/M&A/自社株 수집 추가 (페이지 파라미터 없이 안전하게)
- 카부탄 경고 페이지에서 업적수정 종목 수집
- 민카부 폴백 강화
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
    "上方修正","下方修正","増配","減配","自己株","自社株",
    "TOB","MBO","合併","買収","子会社化","格上げ","格下げ",
    "目標株価引き上げ","目標株価引き下げ",
    "大幅高","大幅安","新高値","年初来高値","年初来安値",
    "業績修正","決算","増資","上場廃止","破産","民事再生",
]
MED_KW = [
    "続伸","続落","反発","反落","堅調","軟調",
    "業績","黒字","赤字","増収","増益","減収","減益",
    "受注","契約","提携","新製品","特許","FDA",
    "売上","利益","成長","拡大","投資","開発","生産",
]

def classify_importance(title: str) -> int:
    if any(kw in title for kw in HIGH_KW): return 3
    if any(kw in title for kw in MED_KW): return 2
    return 1


def fetch_news_market() -> list:
    """카부탄 마켓 속보 (페이지 파라미터 없이 — 봇차단 우회)"""
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


def fetch_gyoseki_correction() -> list:
    """업적수정 종목 수집 (카부탄 경고 페이지)"""
    items = []
    # 업적수정 페이지들 (파라미터 최소화)
    targets = [
        ("上方修正", "https://kabutan.jp/warning/?mode=2_1&market=1"),
        ("下方修正", "https://kabutan.jp/warning/?mode=2_2&market=1"),
        ("増配",     "https://kabutan.jp/warning/?mode=2_3&market=1"),
        ("減配",     "https://kabutan.jp/warning/?mode=2_4&market=1"),
        ("自社株買い", "https://kabutan.jp/warning/?mode=2_5&market=1"),
    ]
    today   = datetime.now(JST).strftime("%Y-%m-%d")
    now_str = datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S")
    seen = set()

    for label, url in targets:
        try:
            r = SESSION.get(url, timeout=15)
            if r.status_code != 200:
                continue
            html = r.text
            trs = re.findall(r'<tr[^>]*>(.*?)</tr>', html, re.DOTALL)
            cnt = 0
            for tr in trs[:20]:
                code_m = re.search(r'code=(\d{4}[A-Z]?)', tr)
                name_m = re.search(r'<a[^>]+stock[^>]+>([^<]+)</a>', tr)
                if not code_m: continue
                code = code_m.group(1)
                name = name_m.group(1).strip() if name_m else code
                title = f"{name} {label}"
                uid = hashlib.md5(f"kab_gyoseki_{today}_{code}_{label}".encode()).hexdigest()[:12]
                if uid in seen: continue
                seen.add(uid)
                items.append({
                    "uid":          uid,
                    "title":        f"[{code}] {title}",
                    "summary":      "",
                    "url":          url,
                    "source":       "kabutan_gyoseki",
                    "published_at": now_str,
                    "stocks":       f'["{code}"]',
                    "importance":   3,
                })
                cnt += 1
            if cnt > 0:
                print(f"  [{label}] {cnt}건")
            time.sleep(1)
        except Exception as e:
            print(f"  [{label}] 오류: {e}")

    print(f"  [업적수정 합계] {len(items)}건")
    return items


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
        for tr in trs[:50]:
            code_m = re.search(r'code=(\d{4}[A-Z]?)', tr)
            if not code_m: continue
            code = code_m.group(1)

            # 종목명: stock 링크에서 추출
            name_m = re.search(r'<a[^>]+stock[^>]+>([^<]{2,30})</a>', tr)
            name = name_m.group(1).strip() if name_m else ""

            # 종목명 없으면 스킵
            if not name or name.replace(",","").replace(".","").replace(" ","").isdigit():
                continue

            # 레이팅 정보 추출 (증권사명, 방향, 목표주가)
            tds = re.findall(r'<td[^>]*>\s*([^<\s][^<]{1,40}?)\s*</td>', tr)
            # 숫자만인 td 제외
            info_parts = []
            for td in tds:
                td = td.strip()
                if not td: continue
                if td.replace(",","").replace(".","").replace(" ","").isdigit(): continue
                if td == code or td == name: continue
                if len(td) >= 2:
                    info_parts.append(td)

            if not info_parts: continue
            info = " ".join(info_parts[:3])
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
    today   = datetime.now(JST).strftime("%Y-%m-%d")
    now_str = datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S")
    for label, url in [
        ("ストップ高", "https://kabutan.jp/warning/?mode=1_2&market=1"),
        ("ストップ安", "https://kabutan.jp/warning/?mode=1_3&market=1"),
    ]:
        try:
            r = SESSION.get(url, timeout=15)
            if r.status_code != 200: continue
            html = r.text
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
        print(f"  [VPS] 전송 스킵 (items={len(items)}, url={VPS_API_URL[:30] if VPS_API_URL else 'None'})")
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
    seen_uids = set()

    # 1. 속보 뉴스 (카부탄 → 민카부 폴백)
    news = fetch_news_market()
    if not news:
        print("  카부탄 실패 → 민카부 시도")
        news = fetch_minkabu_news()
    all_items.extend(news)
    time.sleep(2)

    # 2. 업적수정/결산/自社株 (★ 신규 추가)
    gyoseki = fetch_gyoseki_correction()
    all_items.extend(gyoseki)
    time.sleep(2)

    # 3. 레이팅 변경
    all_items.extend(fetch_rating())
    time.sleep(2)

    # 4. 스톱하이/스톱로
    all_items.extend(fetch_stop_stocks())

    # 중복 제거
    unique = []
    for item in all_items:
        if item["uid"] not in seen_uids:
            seen_uids.add(item["uid"])
            unique.append(item)

    print(f"\n총 {len(unique)}건 수집")
    push_to_vps(unique)
    print("완료")


if __name__ == "__main__":
    main()
