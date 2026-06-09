"""
collect_news.py
GitHub Actions에서 실행 — NHK/Yahoo/Investing.com RSS 수집 → VPS push
평일/주말 관계없이 30분마다 실행
"""
import os, re, time, hashlib, json
from datetime import datetime, timezone, timedelta
import requests
import xml.etree.ElementTree as ET

VPS_API_URL = os.environ.get("VPS_NEWS_API_URL", "https://jpstocklive.com/api")

JST = timezone(timedelta(hours=9))

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
}

RSS_FEEDS = [
    # NHK (www.nhk.or.jp만 작동, www3는 차단됨)
    ("nhk_eco",   "https://www.nhk.or.jp/rss/news/cat6.xml"),   # 경제
    ("nhk_world", "https://www.nhk.or.jp/rss/news/cat4.xml"),   # 국제
    ("nhk_top",   "https://www.nhk.or.jp/rss/news/cat0.xml"),   # 주요
    ("nhk_tech",  "https://www.nhk.or.jp/rss/news/cat3.xml"),   # 과학/기술
    ("nhk_biz",   "https://www.nhk.or.jp/rss/news/cat5.xml"),   # 정치
    # Yahoo Finance JP
    ("yahoo_fin", "https://finance.yahoo.co.jp/rss/news"),
    # Investing.com JP (일본 주식/경제만, 외환 제외)
    ("inv_stock", "https://jp.investing.com/rss/news_14.rss"),  # 주식
    ("inv_econ",  "https://jp.investing.com/rss/news_301.rss"), # 경제
]

# 제외 키워드
EXCLUDE_KW = [
    "サッカー", "野球", "バスケ", "テニス", "ゴルフ", "ラグビー", "五輪",
    "オリンピック", "W杯", "ワールドカップ", "高校野球", "Jリーグ", "プロ野球",
    "芸能", "アイドル", "歌手", "俳優", "映画", "ドラマ", "コンサート",
    "交通事故", "火災", "逮捕", "容疑者", "殺人", "詐欺被害",
    "スポーツ協会", "体育協会",
]

# 중요도 키워드
HIGH_KW = [
    "日銀", "BOJ", "金利", "FOMC", "FRB", "GDP", "CPI", "PCE",
    "利上げ", "利下げ", "関税", "決算", "業績修正", "TOB", "合併",
    "上場廃止", "破産", "民事再生", "円高", "円安", "半導体",
]


def _uid(url: str) -> str:
    return hashlib.md5(url.encode()).hexdigest()[:12]


def _parse_rss(xml_text: str, source: str) -> list:
    items = []
    try:
        # feedparser 없으므로 ET 직접 파싱
        xml_text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', xml_text)
        root = ET.fromstring(xml_text)
        ns_map = {
            'dc': 'http://purl.org/dc/elements/1.1/',
            'content': 'http://purl.org/rss/1.0/modules/content/',
        }
        ch = root.find("channel")
        entries = ch.findall("item") if ch is not None else root.findall(".//item")

        for entry in entries:
            def _t(tag):
                el = entry.find(tag)
                return el.text.strip() if el is not None and el.text else ""

            title = _t("title")
            url   = _t("link") or _t("guid")
            pub   = _t("pubDate") or _t("dc:date") or ""

            if not title or not url:
                continue

            # 날짜 파싱
            pub_dt = None
            for fmt in [
                "%a, %d %b %Y %H:%M:%S %z",
                "%a, %d %b %Y %H:%M:%S %Z",
                "%Y-%m-%dT%H:%M:%S%z",
                "%Y-%m-%dT%H:%M:%SZ",
            ]:
                try:
                    pub_dt = datetime.strptime(pub.strip(), fmt)
                    break
                except ValueError:
                    continue

            if pub_dt is None:
                pub_dt = datetime.now(timezone.utc)

            pub_jst = pub_dt.astimezone(JST)
            pub_str = pub_jst.strftime("%Y-%m-%d %H:%M:%S")

            # 오래된 뉴스 제외 (24시간 이상)
            age_min = int((datetime.now(timezone.utc) - pub_dt.astimezone(timezone.utc)).total_seconds() / 60)
            if age_min > 1440:
                continue

            items.append({
                "uid":          _uid(url),
                "title":        title,
                "summary":      "",
                "url":          url,
                "source":       source,
                "published_at": pub_str,
                "age_min":      age_min,
                "stocks":       "",
                "sectors":      "",
                "score":        2,
            })
    except Exception as e:
        print(f"  [{source}] 파싱 오류: {e}")

    return items


def fetch_rss(source: str, url: str) -> list:
    try:
        res = requests.get(url, headers=HEADERS, timeout=15)
        if res.status_code != 200:
            print(f"  [{source}] HTTP {res.status_code}")
            return []
        items = _parse_rss(res.text, source)

        # 제외 키워드 필터
        filtered = []
        for item in items:
            title = item.get("title", "")
            if any(kw in title for kw in EXCLUDE_KW):
                continue
            # 중요도 점수
            score = 3 if any(kw in title for kw in HIGH_KW) else 2
            item["score"] = score
            filtered.append(item)

        print(f"  [{source}] {len(filtered)}건")
        return filtered
    except Exception as e:
        print(f"  [{source}] 오류: {e}")
        return []


def push_to_vps(items: list) -> dict:
    if not items:
        return {"saved": 0}
    try:
        res = requests.post(
            f"{VPS_API_URL}/push/news",
            json={"items": items},
            timeout=30,
        )
        return res.json()
    except Exception as e:
        print(f"  VPS push 오류: {e}")
        return {"saved": 0}


def main():
    now = datetime.now(JST)
    print(f"=== 뉴스 수집 시작: {now.strftime('%Y-%m-%d %H:%M:%S')} JST ===")

    all_items = []
    seen_uids = set()

    for source, url in RSS_FEEDS:
        items = fetch_rss(source, url)
        for item in items:
            if item["uid"] not in seen_uids:
                seen_uids.add(item["uid"])
                all_items.append(item)
        time.sleep(1)

    print(f"\n총 {len(all_items)}건 수집 (중복 제거)")

    result = push_to_vps(all_items)
    saved = result.get("saved", 0)
    print(f"VPS 저장: {saved}건")
    print("완료")


if __name__ == "__main__":
    main()
