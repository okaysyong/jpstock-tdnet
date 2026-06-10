# -*- coding: utf-8 -*-
"""
collect_stock_news.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
GitHub Actions에서 실행 (5분마다)
카부탄 종목별 뉴스 + 시장 뉴스 수집 → VPS /push/stock_news 전송

수집 소스:
  1. 카부탄 시장 뉴스 (marketnews)         → 시장 전체 재료
  2. 카부탄 거래대금 상위 종목별 뉴스        → 종목 개별 재료
  3. 카부탄 테마주 뉴스                    → 섹터/테마 재료

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
from typing import List, Dict, Optional

# ── 설정 ────────────────────────────────────────────────
VPS_URL    = os.environ.get("VPS_URL", "https://jpstocklive.com")
VPS_SECRET = os.environ.get("VPS_SECRET", "")

JST = timezone(timedelta(hours=9))

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ja,en;q=0.9,ko;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# 거래대금 상위 종목 (Yahoo Finance JP에서 매일 갱신, 없으면 기본값 사용)
# GitHub Actions에서 환경변수로 전달받거나 하드코딩 fallback 사용
DEFAULT_TOP_CODES = [
    "8306",  # 三菱UFJ
    "9984",  # ソフトバンクG
    "6857",  # アドバンテスト
    "8035",  # 東京エレクトロン
    "7203",  # トヨタ自動車
    "6758",  # ソニーG
    "6098",  # リクルートHD
    "9432",  # NTT
    "8766",  # 東京海上HD
    "7974",  # 任天堂
    "6861",  # キーエンス
    "4063",  # 信越化学
    "6920",  # レーザーテック
    "2914",  # JT
    "9433",  # KDDI
    "7267",  # ホンダ
    "3382",  # セブン&アイ
    "8411",  # みずほFG
    "6501",  # 日立製作所
    "4568",  # 第一三共
]

# 뉴스 필터링 - 제외 키워드 (주식시장 무관 뉴스)
_EXCLUDE_KEYWORDS = [
    # 스포츠
    "野球", "サッカー", "バスケット", "テニス", "ゴルフスコア",
    "オリンピック競技", "ワールドカップ試合",
    # 엔터테인먼트
    "芸能", "タレント", "アイドル", "ドラマ", "映画公開",
    # 황실/정치 일반
    "天皇", "皇室", "皇后", "憲法改正議論", "参議院選挙",
    # 사회면
    "事件", "事故", "災害", "地震速報", "台風",
    # 암호화폐 (개별)
    "ビットコイン急騰", "仮想通貨急落", "NFT販売",
]

# 중요도 판별 키워드
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
    """HTML 태그 제거"""
    s = re.sub(r'<[^>]+>', '', s)
    s = re.sub(r'\s+', ' ', s)
    return s.strip()

def _make_id(code: str, title: str, date: str) -> str:
    """뉴스 고유 ID 생성"""
    raw = f"{code}_{title}_{date}"
    return hashlib.md5(raw.encode()).hexdigest()[:12]

def _jst_now() -> str:
    return datetime.now(JST).strftime("%Y-%m-%d %H:%M")

def _fetch_url(url: str, timeout: int = 10) -> Optional[str]:
    """URL fetch (urllib 사용 - requests 없이)"""
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            charset = "utf-8"
            ct = r.headers.get("Content-Type", "")
            if "charset=" in ct:
                charset = ct.split("charset=")[-1].strip()
            return r.read().decode(charset, errors="ignore")
    except Exception as e:
        print(f"  [fetch] {url[:60]}... 실패: {e}")
        return None

def _classify_importance(title: str) -> int:
    """
    뉴스 중요도 분류
    3: 고중요 (결산/수정/TOB 등)
    2: 중중요
    1: 일반
    """
    for kw in _HIGH_IMPACT:
        if kw in title:
            return 3
    for kw in _MEDIUM_IMPACT:
        if kw in title:
            return 2
    return 1

def _is_excluded(title: str) -> bool:
    """제외 대상 뉴스 여부"""
    for kw in _EXCLUDE_KEYWORDS:
        if kw in title:
            return True
    return False


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 1. 카부탄 시장 뉴스 (marketnews)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def fetch_kabutan_market_news() -> List[dict]:
    """
    카부탄 시장 뉴스 수집
    https://kabutan.jp/news/marketnews/
    """
    print("[카부탄] 시장 뉴스 수집 중...")
    url = "https://kabutan.jp/news/marketnews/"
    html = _fetch_url(url)
    if not html:
        return []

    results = []
    today = datetime.now(JST).strftime("%Y-%m-%d")

    # 뉴스 목록 파싱
    # 구조: <div class="news_list"> ... <dl> ... <dt>시각</dt><dd><a href="/news/...">제목</a>
    items = re.findall(
        r'<dt[^>]*>([^<]*\d{2}:\d{2}[^<]*)</dt>\s*<dd[^>]*>.*?<a[^>]+href="(/news/[^"]+)"[^>]*>([^<]+)</a>',
        html, re.DOTALL
    )

    # 대안 파싱: 테이블 구조
    if not items:
        items_alt = re.findall(
            r'href="(/news/marketnews/\?[^"]+)"[^>]*>([^<]{5,80})</a>.*?<span[^>]*>(\d{1,2}:\d{2})',
            html, re.DOTALL
        )
        for href, title, t in items_alt[:30]:
            title = _clean_html(title).strip()
            if not title or _is_excluded(title):
                continue
            news_id = _make_id("market", title, today)
            results.append({
                "id":         news_id,
                "code":       "",
                "company":    "",
                "title":      title,
                "url":        f"https://kabutan.jp{href}",
                "time":       t,
                "date":       today,
                "source":     "kabutan_market",
                "importance": _classify_importance(title),
                "fetched_at": _jst_now(),
            })
        print(f"  → 시장뉴스 {len(results)}건 (대안파싱)")
        return results

    for t, href, title in items[:30]:
        t = _clean_html(t).strip()
        title = _clean_html(title).strip()
        if not title or _is_excluded(title):
            continue
        news_id = _make_id("market", title, today)
        results.append({
            "id":         news_id,
            "code":       "",
            "company":    "",
            "title":      title,
            "url":        f"https://kabutan.jp{href}",
            "time":       t[-5:] if len(t) >= 5 else t,
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
    """
    특정 종목의 카부탄 뉴스 수집
    https://kabutan.jp/stock/news/?code=XXXX
    """
    url = f"https://kabutan.jp/stock/news/?code={code}"
    html = _fetch_url(url, timeout=8)
    if not html:
        return []

    results = []
    today = datetime.now(JST).strftime("%Y-%m-%d")

    # 회사명 추출
    company_m = re.search(r'<h1[^>]*class="[^"]*stockname[^"]*"[^>]*>([^<]+)', html)
    company = _clean_html(company_m.group(1)) if company_m else ""

    # 뉴스 목록 파싱
    # 구조: <table class="news_table"> <tr> <td>날짜시각</td> <td>분류</td> <td><a href>제목</a></td>
    rows = re.findall(
        r'<tr[^>]*>\s*<td[^>]*>(\d{2}/\d{2}\s+\d{2}:\d{2})</td>\s*<td[^>]*>([^<]*)</td>\s*<td[^>]*><a[^>]+href="([^"]+)"[^>]*>([^<]+)</a>',
        html, re.DOTALL
    )

    # 대안 파싱
    if not rows:
        rows_alt = re.findall(
            r'<a[^>]+href="(/news/[^"]+)"[^>]*>([^<]{5,100})</a>',
            html
        )
        for href, title in rows_alt[:10]:
            title = _clean_html(title).strip()
            if not title or len(title) < 5 or _is_excluded(title):
                continue
            news_id = _make_id(code, title, today)
            results.append({
                "id":         news_id,
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

    for dt, category, href, title in rows[:8]:
        title = _clean_html(title).strip()
        category = _clean_html(category).strip()
        if not title or _is_excluded(title):
            continue

        # 날짜 파싱: "06/10 09:35" → "2026-06-10"
        try:
            mm, dd = dt[:5].split("/")
            year = datetime.now(JST).year
            date_str = f"{year}-{mm}-{dd}"
            time_str = dt[6:].strip()
        except Exception:
            date_str = today
            time_str = ""

        news_id = _make_id(code, title, date_str)
        full_url = href if href.startswith("http") else f"https://kabutan.jp{href}"

        results.append({
            "id":         news_id,
            "code":       code,
            "company":    company,
            "title":      title,
            "url":        full_url,
            "time":       time_str,
            "date":       date_str,
            "source":     "kabutan_stock",
            "category":   category,
            "importance": _classify_importance(title),
            "fetched_at": _jst_now(),
        })

    return results


def fetch_all_stock_news(codes: List[str]) -> List[dict]:
    """거래대금 상위 종목 전체 뉴스 수집"""
    print(f"[카부탄] 종목별 뉴스 수집 중... ({len(codes)}종목)")
    all_news = []
    seen_ids = set()

    for i, code in enumerate(codes):
        items = fetch_kabutan_stock_news(code)
        new_items = []
        for item in items:
            if item["id"] not in seen_ids:
                seen_ids.add(item["id"])
                new_items.append(item)
        all_news.extend(new_items)
        print(f"  [{i+1:02d}/{len(codes)}] {code}: {len(new_items)}건")

        # 서버 부하 방지 (0.5초 간격)
        if i < len(codes) - 1:
            time.sleep(0.5)

    print(f"  → 종목뉴스 합계 {len(all_news)}건")
    return all_news


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 3. 카부탄 테마주 뉴스
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def fetch_kabutan_theme_news() -> List[dict]:
    """
    카부탄 테마주 뉴스 수집
    https://kabutan.jp/news/marketnews/?category=theme
    """
    print("[카부탄] 테마주 뉴스 수집 중...")
    url = "https://kabutan.jp/news/marketnews/?category=theme"
    html = _fetch_url(url)
    if not html:
        return []

    results = []
    today = datetime.now(JST).strftime("%Y-%m-%d")

    items = re.findall(
        r'<a[^>]+href="(/news/marketnews/[^"?]+)"[^>]*>([^<]{8,100})</a>',
        html
    )

    seen = set()
    for href, title in items[:20]:
        title = _clean_html(title).strip()
        if not title or title in seen or _is_excluded(title):
            continue
        # 테마 관련 키워드만
        if not any(k in title for k in ["テーマ", "関連株", "関連銘柄", "セクター",
                                          "材料", "注目", "急騰", "ランキング"]):
            continue
        seen.add(title)
        news_id = _make_id("theme", title, today)
        results.append({
            "id":         news_id,
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
    """
    수집한 뉴스를 VPS /push/stock_news 로 전송
    """
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

    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            **HEADERS,
            "Content-Type": "application/json; charset=utf-8",
            "Content-Length": str(len(data)),
        },
        method="POST"
    )

    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            resp = json.loads(r.read().decode())
            print(f"[VPS] 전송 완료: {resp}")
            return True
    except Exception as e:
        print(f"[VPS] 전송 실패: {e}")
        return False


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 거래대금 상위 종목 코드 가져오기 (환경변수 or 기본값)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def get_top_codes() -> List[str]:
    """
    환경변수 TOP_CODES에서 종목 코드 가져오기
    없으면 DEFAULT_TOP_CODES 사용
    형식: "6857,8035,9984,..."
    """
    env_codes = os.environ.get("TOP_CODES", "")
    if env_codes:
        codes = [c.strip() for c in env_codes.split(",") if c.strip()]
        if codes:
            print(f"[설정] 환경변수 종목: {len(codes)}개")
            return codes[:20]
    print(f"[설정] 기본값 종목: {len(DEFAULT_TOP_CODES)}개")
    return DEFAULT_TOP_CODES


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 메인
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def main():
    start = time.time()
    now_jst = datetime.now(JST)
    print(f"━━━ 카부탄 종목뉴스 수집 시작 {now_jst.strftime('%Y-%m-%d %H:%M JST')} ━━━")

    # 수집 대상 종목
    codes = get_top_codes()

    all_news = []

    # 1. 시장 뉴스
    market_news = fetch_kabutan_market_news()
    all_news.extend(market_news)
    time.sleep(0.5)

    # 2. 종목별 뉴스
    stock_news = fetch_all_stock_news(codes)
    all_news.extend(stock_news)
    time.sleep(0.5)

    # 3. 테마주 뉴스
    theme_news = fetch_kabutan_theme_news()
    all_news.extend(theme_news)

    # 중복 제거 (ID 기준)
    seen_ids = set()
    unique_news = []
    for item in all_news:
        if item["id"] not in seen_ids:
            seen_ids.add(item["id"])
            unique_news.append(item)

    # 중요도 내림차순 정렬
    unique_news.sort(key=lambda x: (-x["importance"], x.get("date", ""), x.get("time", "")))

    elapsed = time.time() - start
    print(f"\n━━━ 수집 완료 ━━━")
    print(f"  총 뉴스: {len(unique_news)}건")
    print(f"  중요도3: {len([n for n in unique_news if n['importance'] == 3])}건")
    print(f"  중요도2: {len([n for n in unique_news if n['importance'] == 2])}건")
    print(f"  중요도1: {len([n for n in unique_news if n['importance'] == 1])}건")
    print(f"  소요시간: {elapsed:.1f}초")

    # VPS 전송
    success = push_to_vps(unique_news)

    if not success:
        print("[오류] VPS 전송 실패")
        sys.exit(1)

    print("✅ 완료")


if __name__ == "__main__":
    main()
