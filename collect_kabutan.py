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
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from collector_parsing import article_timestamp, kabutan_articles, stock_code

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

_kabutan_source_valid = False

def classify_importance(title: str) -> int:
    if any(kw in title for kw in HIGH_KW): return 3
    if any(kw in title for kw in MED_KW): return 2
    return 1


def fetch_news_market() -> list:
    """Only source-dated articles from the Kabutan news list."""
    global _kabutan_source_valid
    _kabutan_source_valid = False
    try:
        r = SESSION.get("https://kabutan.jp/news/marketnews/", timeout=15)
        r.raise_for_status()
        articles = list(kabutan_articles(r.text))
        _kabutan_source_valid = bool(articles)
        items = []
        for article in articles:
            title, code = article['title'], article['code']
            imp = classify_importance(title)
            if imp < 2:
                continue
            uid = hashlib.md5(f"kab_{article['date']}_{code}_{title}".encode()).hexdigest()[:12]
            items.append({
                "uid": uid, "title": f"[{code}] {title}" if code else title,
                "summary": "", "url": article['url'], "source": "kabutan_news",
                "published_at": article['published_at'],
                "stocks": [code] if code else [], "score": imp,
            })
        print(f"  [Kabutan] {len(items)} articles")
        return items
    except requests.RequestException:
        print("  [Kabutan] Download failed")
        return []

def fetch_gyoseki_correction() -> list:
    """Retired: warning mode 2_1 is a price ranking, not earnings guidance.

    Guidance changes remain covered by genuine news articles and TDnet.
    A ranking must never be manufactured into a newly published disclosure.
    """
    return []

def fetch_minkabu_news() -> list:
    """Fallback articles only when their own publication time is present."""
    try:
        r = SESSION.get("https://minkabu.jp/news/stock", timeout=15)
        r.raise_for_status()
    except requests.RequestException:
        print("  [Minkabu] Download failed")
        return []
    soup = BeautifulSoup(r.text, 'html.parser')
    items, seen = [], set()
    for anchor in soup.select('a[href]'):
        href = anchor['href']
        if not re.fullmatch(r'/news/[0-9]+', href):
            continue
        title = anchor.get_text(' ', strip=True)
        if len(title) < 5 or classify_importance(title) < 2 or href in seen:
            continue
        # Use the nearest single-article card, never a header or adjacent date.
        card = anchor.parent
        published = None
        for _ in range(5):
            if card is None:
                break
            news_links = {a['href'] for a in card.select('a[href]')
                          if re.fullmatch(r'/news/[0-9]+', a['href'])}
            if news_links != {href}:
                break
            published = article_timestamp(card)
            if published is not None:
                break
            card = card.parent
        if published is None:
            continue
        code = stock_code(str(card))
        day = published.strftime('%Y-%m-%d')
        uid = hashlib.md5(f"minka_{day}_{code}_{title}".encode()).hexdigest()[:12]
        seen.add(href)
        items.append({
            "uid": uid, "title": f"[{code}] {title}" if code else title,
            "summary": "", "url": urljoin('https://minkabu.jp', href),
            "source": "minkabu_news", "published_at": published.strftime('%Y-%m-%d %H:%M:%S'),
            "stocks": [code] if code else [], "score": classify_importance(title),
        })
    print(f"  [Minkabu] {len(items)} source-dated articles")
    return items

def fetch_rating() -> list:
    """Retired: warning mode 6_3 is a moving-average screen, not a rating."""
    return []

def fetch_stop_stocks() -> list:
    """Retired: undated screening pages are not newly published articles."""
    return []

def push_to_vps(items: list):
    from collector_common import push_json
    if not items:
        return {"ok":True,"saved":0,"total":0}
    result=push_json(VPS_API_URL,"/push/news",{"items":items})
    print(f"VPS saved={result.get('saved',0)} duplicate={result.get('duplicates',0)}")
    return result


def main():
    now = datetime.now(JST)
    print(f"=== 카부탄 속보 수집: {now.strftime('%Y-%m-%d %H:%M:%S')} JST ===")
    all_items = []
    seen_uids = set()

    # 1. 속보 뉴스 (카부탄 → 민카부 폴백)
    news = fetch_news_market()
    if not news and _kabutan_source_valid:
        print("Source parsed successfully; no qualifying market news")
        return
    if not news:
        print("  카부탄 실패 → 민카부 시도")
        news = fetch_minkabu_news()
    all_items.extend(news)
    time.sleep(2)

    # Financial claims come from genuine dated articles and TDnet. Warning
    # screens must not be transformed into newly published financial news.

    unique = []
    for item in all_items:
        if item["uid"] not in seen_uids:
            seen_uids.add(item["uid"])
            unique.append(item)

    print(f"\n총 {len(unique)}건 수집")
    if not unique:
        raise RuntimeError('No market news parsed from any source; verify upstream availability')
    push_to_vps(unique)
    print("완료")


if __name__ == "__main__":
    main()
