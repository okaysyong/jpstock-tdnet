# -*- coding: utf-8 -*-
"""
collect_stock_news.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
GitHub Actions에서 실행 (5분마다)
카부탄 종목별 뉴스 + 시장 뉴스 수집 → VPS /push/stock_news 전송

수집 소스:
  1. 카부탄 시장 뉴스 (marketnews)
  2. 카부탄 거래대금 상위 종목별 뉴스
  3. 카부탄 테마주 뉴스

VPS 수신: POST https://jpstocklive.com/push/stock_news
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import os
import re
import sys
import json
import time
import hashlib
import urllib.request
import urllib.parse
from datetime import datetime, timezone, timedelta
from typing import List, Optional

# requests 사용 (GitHub Actions 기본 포함)
try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

# ── 설정 ────────────────────────────────────────────────
VPS_URL    = os.environ.get("VPS_URL", "https://jpstocklive.com")
VPS_SECRET = os.environ.get("VPS_SECRET", "")

JST = timezone(timedelta(hours=9))

# 카부탄 차단 우회용 헤더 (실제 브라우저와 최대한 동일하게)
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Cache-Control": "max-age=0",
}

# 닛케이225 전종목 + 주요 추가 종목
NK225_CODES = [
    "1332","1333","1605","1721","1801","1802","1803","1808","1812","1925",
    "1928","1963","2002","2269","2282","2413","2432","2501","2502","2503",
    "2531","2768","2801","2802","2871","2914","3086","3092","3099","3289",
    "3382","3401","3402","3405","3407","3436","3659","3861","3863","4004",
    "4005","4021","4042","4043","4061","4062","4063","4183","4188","4208",
    "4324","4452","4502","4503","4506","4507","4519","4523","4543","4568",
    "4578","4631","4642","4661","4689","4704","4751","4755","4901","4902",
    "4911","5001","5020","5101","5105","5108","5201","5202","5214","5232",
    "5233","5301","5332","5333","5401","5406","5411","5541","5631","5714",
    "5715","5801","5802","5803","5831","6098","6103","6113","6146","6178",
    "6273","6301","6302","6305","6326","6361","6367","6471","6472","6473",
    "6479","6501","6503","6504","6506","6645","6674","6701","6702","6703",
    "6724","6752","6753","6754","6758","6762","6770","6796","6841","6857",
    "6861","6902","6920","6952","6954","6971","6976","6981","6988","7003",
    "7004","7011","7012","7013","7186","7201","7202","7203","7205","7211",
    "7261","7267","7269","7270","7272","7731","7733","7735","7741","7751",
    "7752","7762","7832","7911","7912","7974","8001","8002","8003","8005",
    "8006","8007","8008","8010","8015","8031","8035","8053","8056","8058",
    "8060","8233","8252","8253","8267","8301","8304","8306","8308","8309",
    "8316","8331","8354","8355","8411","8591","8601","8604","8628","8630",
    "8697","8750","8766","8795","8802","8804","8830","9001","9005","9007",
    "9008","9009","9020","9021","9022","9064","9101","9104","9107","9202",
    "9301","9432","9433","9434","9501","9502","9503","9531","9532","9602",
    "9613","9633","9735","9766","9983","9984",
    # 추가 주요 종목 (거래대금 상위 자주 등장)
    "285A","6976","5803","6146","4062","6740",
]

DEFAULT_TOP_CODES = NK225_CODES

_EXCLUDE_KEYWORDS = [
    "野球", "サッカー", "バスケット", "テニス", "ゴルフスコア",
    "芸能", "タレント", "アイドル", "ドラマ", "映画公開",
    "天皇", "皇室", "憲法改正議論",
    "交通事故", "火災", "逮捕",
    "ビットコイン急騰", "仮想通貨急落",
]

_HIGH_IMPACT = [
    "業績修正", "上方修正", "下方修正", "決算", "TOB", "買収",
    "増資", "自社株買い", "配当修正", "社長交代", "合併", "分割",
    "受注", "契約", "提携", "新製品", "FDA承認", "特許",
]

_MEDIUM_IMPACT = [
    "売上", "利益", "成長", "拡大", "投資", "開発", "生産",
    "輸出", "輸入", "価格", "需要", "供給", "市況",
]

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 유틸리티
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _clean_html(s: str) -> str:
    s = re.sub(r'<[^>]+>', '', s)
    return re.sub(r'\s+', ' ', s).strip()

def _make_id(code: str, title: str, date: str) -> str:
    raw = f"{code}_{title}_{date}"
    return hashlib.md5(raw.encode()).hexdigest()[:12]

def _jst_now() -> str:
    return datetime.now(JST).strftime("%Y-%m-%d %H:%M")

def _classify_importance(title: str) -> int:
    for kw in _HIGH_IMPACT:
        if kw in title:
            return 3
    for kw in _MEDIUM_IMPACT:
        if kw in title:
            return 2
    return 1

def _is_excluded(title: str) -> bool:
    return any(kw in title for kw in _EXCLUDE_KEYWORDS)

# requests 세션 (재사용으로 연결 효율 향상)
_session = None

def _get_session():
    global _session
    if _session is None:
        if HAS_REQUESTS:
            _session = requests.Session()
            _session.headers.update(HEADERS)
        else:
            _session = False
    return _session

def _fetch_url(url: str, timeout: int = 12) -> Optional[str]:
    """URL fetch — requests 우선, urllib 폴백"""
    sess = _get_session()

    # requests 사용
    if sess:
        try:
            r = sess.get(url, timeout=timeout, allow_redirects=True)
            r.raise_for_status()
            r.encoding = r.apparent_encoding or "utf-8"
            return r.text
        except Exception as e:
            print(f"  [fetch] {url[:70]}... 실패: {e}")
            return None

    # urllib 폴백
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            charset = "utf-8"
            ct = r.headers.get("Content-Type", "")
            if "charset=" in ct:
                charset = ct.split("charset=")[-1].strip()
            return r.read().decode(charset, errors="ignore")
    except Exception as e:
        print(f"  [fetch] {url[:70]}... 실패: {e}")
        return None


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 1. 카부탄 시장 뉴스
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def fetch_kabutan_market_news() -> List[dict]:
    print("[카부탄] 시장 뉴스 수집 중...")
    url = "https://kabutan.jp/news/marketnews/"
    html = _fetch_url(url)
    if not html:
        return []

    results = []
    today = datetime.now(JST).strftime("%Y-%m-%d")

    # 디버그: HTML 크기 및 앞부분 확인
    print(f"  [디버그] HTML 크기: {len(html)}bytes")
    # 카부탄 뉴스 링크 존재 여부 확인
    news_links = re.findall(r'href="(/news/[^"]+)"', html)
    print(f"  [디버그] /news/ 링크 수: {len(news_links)}")
    if news_links:
        print(f"  [디버그] 링크 예시: {news_links[:3]}")

    # 패턴 1: <dt>시각</dt><dd><a href>제목</a>
    items = re.findall(
        r'<dt[^>]*>\s*([^<]*\d{1,2}:\d{2}[^<]*)\s*</dt>\s*<dd[^>]*>.*?'
        r'<a[^>]+href="(/news/[^"]+)"[^>]*>([^<]+)</a>',
        html, re.DOTALL
    )
    print(f"  [디버그] 패턴1 매칭: {len(items)}건")

    # 패턴 2: href와 제목 직접 추출
    if not items:
        items2 = re.findall(
            r'href="(/news/marketnews/\?[^"]+)"[^>]*>\s*([^<]{5,80})\s*</a>',
            html
        )
        for href, title in items2[:30]:
            title = _clean_html(title)
            if not title or _is_excluded(title):
                continue
            results.append({
                "id":         _make_id("market", title, today),
                "code":       "",
                "company":    "",
                "title":      title,
                "url":        f"https://kabutan.jp{href}",
                "time":       "",
                "date":       today,
                "source":     "kabutan_market",
                "importance": _classify_importance(title),
                "fetched_at": _jst_now(),
            })
        print(f"  → 시장뉴스 {len(results)}건 (패턴2)")
        return results

    for t, href, title in items[:30]:
        title = _clean_html(title)
        if not title or _is_excluded(title):
            continue
        time_str = t.strip()[-5:] if len(t.strip()) >= 5 else t.strip()
        results.append({
            "id":         _make_id("market", title, today),
            "code":       "",
            "company":    "",
            "title":      title,
            "url":        f"https://kabutan.jp{href}",
            "time":       time_str,
            "date":       today,
            "source":     "kabutan_market",
            "importance": _classify_importance(title),
            "fetched_at": _jst_now(),
        })

    print(f"  → 시장뉴스 {len(results)}건")
    return results


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 2. 카부탄 종목별 뉴스
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def fetch_kabutan_stock_news(code: str) -> List[dict]:
    url = f"https://kabutan.jp/stock/news/?code={code}"
    html = _fetch_url(url, timeout=10)
    if not html:
        return []

    results = []
    today = datetime.now(JST).strftime("%Y-%m-%d")

    # 회사명 추출
    company_m = re.search(
        r'<h2[^>]*class="[^"]*company_name[^"]*"[^>]*>([^<]+)|'
        r'<title>([^<（(]+)[（(]',
        html
    )
    company = ""
    if company_m:
        company = _clean_html(company_m.group(1) or company_m.group(2) or "")

    # 뉴스 행 파싱: 날짜시각 | 분류 | 제목링크
    rows = re.findall(
        r'<tr[^>]*>\s*<td[^>]*>(\d{2}/\d{2}\s+\d{2}:\d{2})</td>\s*'
        r'<td[^>]*>([^<]*)</td>\s*<td[^>]*><a[^>]+href="([^"]+)"[^>]*>([^<]+)</a>',
        html, re.DOTALL
    )

    if not rows:
        # 폴백: a 태그 직접 추출
        links = re.findall(
            r'<a[^>]+href="(/news/[^"?]+)"[^>]*>([^<]{5,100})</a>',
            html
        )
        for href, title in links[:8]:
            title = _clean_html(title)
            if not title or len(title) < 5 or _is_excluded(title):
                continue
            results.append({
                "id":         _make_id(code, title, today),
                "code":       code,
                "company":    company,
                "title":      title,
                "url":        f"https://kabutan.jp{href}",
                "time":       "",
                "date":       today,
                "source":     "kabutan_stock",
                "importance": _classify_importance(title),
                "fetched_at": _jst_now(),
            })
        return results[:5]

    for dt_str, category, href, title in rows[:8]:
        title = _clean_html(title)
        if not title or _is_excluded(title):
            continue
        try:
            mm, rest = dt_str.strip().split("/")
            dd, time_str = rest.strip().split(" ")
            year = datetime.now(JST).year
            date_str = f"{year}-{mm}-{dd}"
        except Exception:
            date_str = today
            time_str = ""

        full_url = href if href.startswith("http") else f"https://kabutan.jp{href}"
        results.append({
            "id":         _make_id(code, title, date_str),
            "code":       code,
            "company":    company,
            "title":      title,
            "url":        full_url,
            "time":       time_str.strip(),
            "date":       date_str,
            "source":     "kabutan_stock",
            "category":   _clean_html(category),
            "importance": _classify_importance(title),
            "fetched_at": _jst_now(),
        })

    return results


def fetch_all_stock_news(codes: List[str]) -> List[dict]:
    print(f"[카부탄] 종목별 뉴스 수집 중... ({len(codes)}종목)")
    all_news = []
    seen_ids = set()

    for i, code in enumerate(codes):
        items = fetch_kabutan_stock_news(code)
        new_items = [x for x in items if x["id"] not in seen_ids]
        for x in new_items:
            seen_ids.add(x["id"])
        all_news.extend(new_items)
        print(f"  [{i+1:02d}/{len(codes)}] {code}: {len(new_items)}건")
        if i < len(codes) - 1:
            time.sleep(0.8)

    print(f"  → 종목뉴스 합계 {len(all_news)}건")
    return all_news


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 3. 카부탄 테마주 뉴스
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def fetch_kabutan_theme_news() -> List[dict]:
    print("[카부탄] 테마주 뉴스 수집 중...")
    url = "https://kabutan.jp/news/marketnews/?category=theme"
    html = _fetch_url(url)
    if not html:
        return []

    results = []
    today = datetime.now(JST).strftime("%Y-%m-%d")
    seen = set()

    items = re.findall(
        r'href="(/news/marketnews/[^"?]+)"[^>]*>\s*([^<]{8,100})\s*</a>',
        html
    )
    for href, title in items[:20]:
        title = _clean_html(title)
        if not title or title in seen or _is_excluded(title):
            continue
        if not any(k in title for k in ["テーマ", "関連株", "関連銘柄", "セクター",
                                          "材料", "注目", "急騰", "ランキング"]):
            continue
        seen.add(title)
        results.append({
            "id":         _make_id("theme", title, today),
            "code":       "",
            "company":    "",
            "title":      title,
            "url":        f"https://kabutan.jp{href}",
            "time":       "",
            "date":       today,
            "source":     "kabutan_theme",
            "importance": 2,
            "fetched_at": _jst_now(),
        })

    print(f"  → 테마뉴스 {len(results)}건")
    return results


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 4. VPS 전송
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def push_to_vps(news_items: List[dict]) -> bool:
    if not news_items:
        print("[VPS] 전송할 뉴스 없음")
        return True

    url = f"{VPS_URL}/push/stock_news"
    payload = {
        "secret":     VPS_SECRET,
        "news":       news_items,
        "count":      len(news_items),
        "fetched_at": _jst_now(),
        "sources": {
            "market": len([n for n in news_items if n["source"] == "kabutan_market"]),
            "stock":  len([n for n in news_items if n["source"] == "kabutan_stock"]),
            "theme":  len([n for n in news_items if n["source"] == "kabutan_theme"]),
        }
    }

    sess = _get_session()
    if sess:
        try:
            r = sess.post(url, json=payload, timeout=15)
            r.raise_for_status()
            print(f"[VPS] 전송 완료: {r.json()}")
            return True
        except Exception as e:
            print(f"[VPS] 전송 실패: {e}")
            return False

    # urllib 폴백
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url, data=data,
        headers={**HEADERS, "Content-Type": "application/json; charset=utf-8"},
        method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            print(f"[VPS] 전송 완료: {json.loads(r.read().decode())}")
            return True
    except Exception as e:
        print(f"[VPS] 전송 실패: {e}")
        return False


def get_top_codes() -> List[str]:
    """
    거래대금 상위 종목 코드 가져오기
    1순위: VPS /cache의 volume_ranking (실시간)
    2순위: 환경변수 TOP_CODES
    3순위: DEFAULT_TOP_CODES (하드코딩 fallback)
    """
    # 1. VPS 캐시에서 실시간 거래대금 상위 종목 조회
    try:
        sess = _get_session()
        cache_url = f"{VPS_URL}/cache"
        if sess:
            r = sess.get(cache_url, timeout=8)
            r.raise_for_status()
            data = r.json()
        else:
            req = urllib.request.Request(cache_url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=8) as resp:
                data = json.loads(resp.read().decode())

        for item in data.get("items", []):
            if item.get("type") == "volume_ranking":
                codes = [
                    str(s["code"]) for s in item.get("items", [])
                    if s.get("code") and str(s["code"]).replace("A","").replace("B","").isdigit()
                ]
                if codes:
                    print(f"[설정] VPS 거래대금 상위 종목: {len(codes)}개 → NK225 전체와 합산")
                    # 거래대금 상위 + NK225 합산 (중복 제거)
                    merged = list(dict.fromkeys(codes + NK225_CODES))
                    print(f"  → 총 {len(merged)}개 종목")
                    return merged
    except Exception as e:
        print(f"[설정] VPS 캐시 조회 실패: {e}")

    # 2. 환경변수 TOP_CODES
    env_codes = os.environ.get("TOP_CODES", "")
    if env_codes:
        codes = [c.strip() for c in env_codes.split(",") if c.strip()]
        if codes:
            print(f"[설정] 환경변수 종목: {len(codes)}개")
            return codes

    # 3. 기본값
    print(f"[설정] 기본값 종목: {len(DEFAULT_TOP_CODES)}개")
    return DEFAULT_TOP_CODES


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 메인
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def main():
    start = time.time()
    now_jst = datetime.now(JST)
    print(f"━━━ 카부탄 종목뉴스 수집 시작 {now_jst.strftime('%Y-%m-%d %H:%M JST')} ━━━")
    print(f"requests 라이브러리: {'✅ 사용' if HAS_REQUESTS else '❌ urllib 폴백'}")

    codes = get_top_codes()
    all_news = []

    market_news = fetch_kabutan_market_news()
    all_news.extend(market_news)
    time.sleep(1)

    stock_news = fetch_all_stock_news(codes)
    all_news.extend(stock_news)
    time.sleep(1)

    theme_news = fetch_kabutan_theme_news()
    all_news.extend(theme_news)

    # 중복 제거
    seen_ids = set()
    unique_news = []
    for item in all_news:
        if item["id"] not in seen_ids:
            seen_ids.add(item["id"])
            unique_news.append(item)

    unique_news.sort(key=lambda x: (-x["importance"], x.get("date",""), x.get("time","")))

    elapsed = time.time() - start
    print(f"\n━━━ 수집 완료 ━━━")
    print(f"  총 뉴스: {len(unique_news)}건")
    print(f"  중요도3: {len([n for n in unique_news if n['importance']==3])}건")
    print(f"  중요도2: {len([n for n in unique_news if n['importance']==2])}건")
    print(f"  중요도1: {len([n for n in unique_news if n['importance']==1])}건")
    print(f"  소요시간: {elapsed:.1f}초")

    if not push_to_vps(unique_news):
        print("[오류] VPS 전송 실패")
        sys.exit(1)

    print("✅ 완료")


if __name__ == "__main__":
    main()
