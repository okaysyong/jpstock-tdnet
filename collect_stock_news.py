# -*- coding: utf-8 -*-
"""
collect_stock_news.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
GitHub Actions에서 실행 (5분마다)
카부탄 뉴스 수집 → VPS /push/stock_news 전송

전략 (요청 최소화):
  1. 카부탄 시장뉴스 목록 페이지 (10~15페이지) → 종목코드 파싱
  2. 카부탄 전체뉴스 목록 (페이지 순회) → 종목코드 파싱
  → 종목별 개별 요청 없이 대량 수집
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import os, re, sys, json, time, hashlib, urllib.request
from datetime import datetime, timezone, timedelta
from typing import List, Optional

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

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
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}

# 닛케이225 전종목 (파싱된 뉴스의 종목코드 필터링용)
NK225_CODES = set([
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
    # 추가 주요 종목
    "285A","6976","5803","6146","4062","6740","6975","4151","4528",
])

_EXCLUDE_KEYWORDS = [
    "野球","サッカー","バスケット","テニス","芸能","タレント","アイドル",
    "ドラマ","映画公開","天皇","皇室","交通事故","火災","逮捕",
    "ビットコイン急騰","仮想通貨急落",
]

_HIGH_IMPACT = [
    "業績修正","上方修正","下方修正","決算","TOB","買収",
    "増資","自社株買い","配当修正","社長交代","合併","分割",
    "受注","契約","提携","新製品","特許","FDA",
]

_MEDIUM_IMPACT = [
    "売上","利益","成長","拡大","投資","開発","生産",
    "輸出","輸入","価格","需要","供給","市況","増収","増益",
]

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 유틸리티
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _clean(s: str) -> str:
    return re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', '', s)).strip()

def _make_id(code: str, title: str, date: str) -> str:
    return hashlib.md5(f"{code}_{title}_{date}".encode()).hexdigest()[:12]

def _jst_now() -> str:
    return datetime.now(JST).strftime("%Y-%m-%d %H:%M")

def _today() -> str:
    return datetime.now(JST).strftime("%Y-%m-%d")

def _classify(title: str) -> int:
    for kw in _HIGH_IMPACT:
        if kw in title: return 3
    for kw in _MEDIUM_IMPACT:
        if kw in title: return 2
    return 1

def _excluded(title: str) -> bool:
    return any(kw in title for kw in _EXCLUDE_KEYWORDS)

_session = None
def _sess():
    global _session
    if _session is None:
        if HAS_REQUESTS:
            _session = requests.Session()
            _session.headers.update(HEADERS)
        else:
            _session = False
    return _session

def _fetch(url: str, timeout: int = 12) -> Optional[str]:
    s = _sess()
    if s:
        try:
            r = s.get(url, timeout=timeout, allow_redirects=True)
            r.raise_for_status()
            r.encoding = r.apparent_encoding or "utf-8"
            return r.text
        except Exception as e:
            print(f"  [fetch 실패] {url[:70]}: {e}")
            return None
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode("utf-8", errors="ignore")
    except Exception as e:
        print(f"  [fetch 실패] {url[:70]}: {e}")
        return None


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 핵심: 카부탄 뉴스 목록 페이지 파싱
# 한 페이지에서 종목코드 + 뉴스제목을 한꺼번에 추출
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _parse_news_list(html: str, source: str) -> List[dict]:
    """
    카부탄 뉴스 목록 HTML에서 뉴스 파싱
    URL 패턴: /news/marketnews/?&b=nXXXXXXXX (시장뉴스)
              /stock/news/?code=XXXX (종목뉴스 링크)
    """
    results = []
    today = _today()

    # ── 방법1: 뉴스 목록 테이블 행 파싱 ──
    # 구조: <tr> <td>시각</td> <td><a href="/news/...">제목</a></td> <td>종목코드</td>
    rows = re.findall(
        r'<tr[^>]*>.*?</tr>',
        html, re.DOTALL
    )

    for row in rows:
        # 제목과 링크 추출
        title_m = re.search(
            r'href="(/news/[^"]+)"[^>]*>\s*([^<]{5,120})\s*</a>',
            row
        )
        if not title_m:
            continue
        href, title = title_m.group(1), _clean(title_m.group(2))
        if not title or len(title) < 5 or _excluded(title):
            continue

        # 시각 추출
        time_m = re.search(r'(\d{1,2}:\d{2})', row)
        time_str = time_m.group(1) if time_m else ""

        # 종목코드 추출 (행 안의 /stock/ 링크에서)
        code_m = re.search(r'/stock/[^/]+/\?code=(\d{4}[A-Z]?)', row)
        code = code_m.group(1) if code_m else ""

        # 뉴스 URL에서도 종목코드 추출 시도
        if not code:
            code_m2 = re.search(r'[?&]code=(\d{4}[A-Z]?)', href)
            code = code_m2.group(1) if code_m2 else ""

        news_id = _make_id(code or "market", title, today)
        results.append({
            "id":         news_id,
            "code":       code,
            "company":    "",
            "title":      title,
            "url":        f"https://kabutan.jp{href}",
            "time":       time_str,
            "date":       today,
            "source":     source,
            "importance": _classify(title),
            "fetched_at": _jst_now(),
        })

    # ── 방법2: 단순 링크+제목 추출 (방법1 결과가 적을 때) ──
    if len(results) < 5:
        results = []
        links = re.findall(
            r'href="(/news/[^"?]{10,})"[^>]*>\s*([^<]{8,120})\s*</a>',
            html
        )
        seen = set()
        for href, title in links:
            title = _clean(title)
            if not title or title in seen or _excluded(title) or len(title) < 8:
                continue
            # 너무 짧거나 메뉴 항목 같은 것 제외
            if title in ["マーケット", "株式", "ニュース", "ランキング", "続きを読む"]:
                continue
            seen.add(title)

            code_m = re.search(r'[?&]code=(\d{4}[A-Z]?)', href)
            code = code_m.group(1) if code_m else ""

            results.append({
                "id":         _make_id(code or "market", title, today),
                "code":       code,
                "company":    "",
                "title":      title,
                "url":        f"https://kabutan.jp{href}",
                "time":       "",
                "date":       today,
                "source":     source,
                "importance": _classify(title),
                "fetched_at": _jst_now(),
            })

    return results


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 1. 카부탄 시장뉴스 목록 (페이지 순회)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def fetch_market_news_pages(max_pages: int = 15) -> List[dict]:
    """
    카부탄 시장뉴스 목록을 페이지 순회하며 수집
    https://kabutan.jp/news/marketnews/?page=N
    → 1페이지 약 20건, 15페이지 = 최대 300건
    """
    print(f"[카부탄] 시장뉴스 목록 수집 중... (최대 {max_pages}페이지)")
    all_items = []
    seen_ids = set()

    for page in range(1, max_pages + 1):
        url = f"https://kabutan.jp/news/marketnews/?page={page}"
        html = _fetch(url)
        if not html:
            print(f"  페이지 {page}: 실패")
            break

        items = _parse_news_list(html, "kabutan_market")
        new = [x for x in items if x["id"] not in seen_ids]
        for x in new:
            seen_ids.add(x["id"])
        all_items.extend(new)

        print(f"  페이지 {page}: {len(new)}건 (누계 {len(all_items)}건)")

        # 마지막 페이지 감지 (결과 없으면 종료)
        if len(items) == 0:
            break

        # 요청 간격 (카부탄 봇 감지 방지)
        time.sleep(2)

    print(f"  → 시장뉴스 합계 {len(all_items)}건")
    return all_items


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 2. 카부탄 종목별 뉴스 목록 (카테고리별 페이지)
#    개별 종목 페이지 요청 없이 전체 목록에서 파싱
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def fetch_stock_news_pages(max_pages: int = 10) -> List[dict]:
    """
    카부탄 종목뉴스 카테고리 목록 수집
    https://kabutan.jp/news/?category=0&page=N
    → 종목 관련 전체 뉴스 (결산, 業績修正 등 포함)
    """
    print(f"[카부탄] 종목뉴스 목록 수집 중... (최대 {max_pages}페이지)")
    all_items = []
    seen_ids = set()

    # 카테고리별 수집
    categories = [
        ("0",  "결산/업적"),
        ("2",  "M&A/TOB"),
        ("3",  "増資/自社株"),
        ("6",  "株主総会"),
        ("10", "テーマ株"),
    ]

    for cat_id, cat_name in categories:
        cat_count = 0
        for page in range(1, max_pages + 1):
            url = f"https://kabutan.jp/news/?category={cat_id}&page={page}"
            html = _fetch(url)
            if not html:
                break

            items = _parse_news_list(html, "kabutan_stock")
            # NK225 종목 관련 뉴스만 (또는 종목코드 없는 것도 포함)
            filtered = []
            for x in items:
                if x["id"] in seen_ids:
                    continue
                # 종목코드 있으면 NK225 여부 확인 (없으면 포함)
                if x["code"] and x["code"] not in NK225_CODES:
                    continue
                seen_ids.add(x["id"])
                x["source"] = "kabutan_stock"
                filtered.append(x)

            all_items.extend(filtered)
            cat_count += len(filtered)

            if len(items) == 0:
                break
            time.sleep(2)

        print(f"  [{cat_name}]: {cat_count}건")

    print(f"  → 종목뉴스 합계 {len(all_items)}건")
    return all_items


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 3. VPS 캐시에서 거래대금 상위 종목 가져오기 (보조)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def get_top_codes_from_vps() -> List[str]:
    try:
        s = _sess()
        url = f"{VPS_URL}/cache"
        data = s.get(url, timeout=8).json() if s else json.loads(_fetch(url) or "{}")
        for item in data.get("items", []):
            if item.get("type") == "volume_ranking":
                codes = [str(x["code"]) for x in item.get("items", []) if x.get("code")]
                if codes:
                    print(f"[VPS] 거래대금 상위 {len(codes)}개 종목 확인")
                    return codes
    except Exception as e:
        print(f"[VPS] 캐시 조회 실패: {e}")
    return []


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
        }
    }
    s = _sess()
    try:
        if s:
            r = s.post(url, json=payload, timeout=15)
            r.raise_for_status()
            print(f"[VPS] 전송 완료: {r.json()}")
        else:
            data = json.dumps(payload, ensure_ascii=False).encode()
            req = urllib.request.Request(url, data=data,
                headers={**HEADERS, "Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=15) as r:
                print(f"[VPS] 전송 완료: {json.loads(r.read().decode())}")
        return True
    except Exception as e:
        print(f"[VPS] 전송 실패: {e}")
        return False


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 메인
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def main():
    start = time.time()
    now_jst = datetime.now(JST)
    print(f"━━━ 카부탄 뉴스 수집 시작 {now_jst.strftime('%Y-%m-%d %H:%M JST')} ━━━")
    print(f"requests: {'✅' if HAS_REQUESTS else '❌ urllib 폴백'}")

    # VPS에서 거래대금 상위 종목 확인 (NK225에 추가)
    top_codes = get_top_codes_from_vps()
    if top_codes:
        NK225_CODES.update(top_codes)
        print(f"  → 감시 종목 총 {len(NK225_CODES)}개")

    all_news = []

    # 1. 시장뉴스 목록 (15페이지)
    market_news = fetch_market_news_pages(max_pages=15)
    all_news.extend(market_news)

    # 2. 종목뉴스 카테고리 목록
    stock_news = fetch_stock_news_pages(max_pages=5)
    all_news.extend(stock_news)

    # 중복 제거
    seen_ids = set()
    unique = []
    for item in all_news:
        if item["id"] not in seen_ids:
            seen_ids.add(item["id"])
            unique.append(item)

    unique.sort(key=lambda x: (-x["importance"], x.get("time", "")))

    elapsed = time.time() - start
    print(f"\n━━━ 수집 완료 ━━━")
    print(f"  총 뉴스: {len(unique)}건")
    print(f"  중요도3: {len([n for n in unique if n['importance']==3])}건")
    print(f"  중요도2: {len([n for n in unique if n['importance']==2])}건")
    print(f"  중요도1: {len([n for n in unique if n['importance']==1])}건")
    print(f"  소요시간: {elapsed:.1f}초")

    if not push_to_vps(unique):
        sys.exit(1)
    print("✅ 완료")

if __name__ == "__main__":
    main()
