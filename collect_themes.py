"""
collect_themes.py
GitHub Actions에서 실행 — 카부탄에서 종목 테마 수집 → VPS /push/themes
닛케이225 + 거래대금 상위 종목 우선 수집
"""
import os, re, time, json, requests, hashlib, sys
from datetime import datetime
from zoneinfo import ZoneInfo

JST = ZoneInfo("Asia/Tokyo")
VPS_API_URL = os.environ.get("VPS_NEWS_API_URL", "")
VPS_TOKEN   = os.environ.get("VPS_TOKEN", "")

def log(msg):
    log(msg, flush=True)

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ja-JP,ja;q=0.9,en-US;q=0.8",
    "Connection": "keep-alive",
})

# ── 닛케이225 전종목 ──────────────────────────────
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
    # 추가 주요 종목 (거래대금 상위)
    "285A","6976","5803","6146","4062","6740","6975","4151","4528",
    "5016","6857","6920","8035","1570","9984","6981","6976",
]

def fetch_kabutan_themes(code: str) -> list:
    """카부탄 종목 페이지에서 関連テーマ 파싱"""
    url = f"https://kabutan.jp/stock/?code={code}"
    try:
        r = SESSION.get(url, timeout=15)
        if r.status_code != 200:
            return []
        html = r.text

        themes = []

        # ① 関連テーマ 섹션 파싱
        # 패턴: <div class="theme_label">...</div> 또는 테마 링크
        theme_section = re.search(
            r'関連テーマ.*?</(?:div|section|table)>',
            html, re.DOTALL
        )
        if theme_section:
            theme_links = re.findall(
                r'<a[^>]+theme[^>]*>([^<]{2,20})</a>',
                theme_section.group(0)
            )
            themes.extend([t.strip() for t in theme_links if t.strip()])

        # ② テーマ株 링크에서 추출
        theme_links2 = re.findall(
            r'/themes/\d+[^"]*"[^>]*>([^<]{2,20})</a>',
            html
        )
        themes.extend([t.strip() for t in theme_links2 if t.strip()])

        # ③ data-theme 속성에서 추출
        data_themes = re.findall(r'data-theme="([^"]{2,20})"', html)
        themes.extend(data_themes)

        # 중복 제거 + 정리
        seen = set()
        result = []
        for t in themes:
            t = t.strip()
            if t and t not in seen and len(t) >= 2 and len(t) <= 20:
                # 일반적인 메뉴 항목 제외
                if t not in ["テーマ株","株式","銘柄","ランキング","マーケット","ニュース"]:
                    seen.add(t)
                    result.append(t)

        return result[:10]

    except Exception as e:
        log(f"  [테마] {code} 오류: {e}")
        return []


def fetch_minkabu_themes(code: str) -> list:
    """민카부 종목 페이지에서 테마 파싱 (카부탄 보완)"""
    url = f"https://minkabu.jp/stock/{code}"
    try:
        r = SESSION.get(url, timeout=15)
        if r.status_code != 200:
            return []
        html = r.text

        themes = []
        # 민카부 테마 링크
        theme_links = re.findall(
            r'/themes/[^"]+">([^<]{2,20})</a>',
            html
        )
        themes.extend([t.strip() for t in theme_links if t.strip()])

        # 관련 키워드
        kw_section = re.search(r'関連キーワード.*?</(?:div|ul)>', html, re.DOTALL)
        if kw_section:
            kws = re.findall(r'>([^<]{2,15})</(?:a|li|span)>', kw_section.group(0))
            themes.extend([k.strip() for k in kws if k.strip()])

        seen = set()
        result = []
        for t in themes:
            t = t.strip()
            if t and t not in seen and 2 <= len(t) <= 20:
                seen.add(t)
                result.append(t)
        return result[:10]

    except Exception as e:
        return []


def get_top_codes_from_vps() -> list:
    """VPS에서 거래대금 상위 종목 가져오기"""
    try:
        r = SESSION.get(f"{VPS_API_URL}/cache", timeout=8)
        if r.status_code != 200:
            return []
        data = r.json()
        for item in data.get("items", []):
            if item.get("type") == "volume_ranking":
                codes = [str(x["code"])[:4] for x in item.get("items", []) if x.get("code")]
                if codes:
                    log(f"  [VPS] 거래대금 상위 {len(codes)}개 종목")
                    return codes
    except Exception as e:
        log(f"  [VPS] 캐시 조회 실패: {e}")
    return []


def push_to_vps(items: list) -> None:
    if not items or not VPS_API_URL:
        return
    try:
        headers = {"Content-Type": "application/json"}
        if VPS_TOKEN:
            headers["X-Push-Token"] = VPS_TOKEN
        res = SESSION.post(
            f"{VPS_API_URL}/push/themes",
            json={"items": items},
            headers=headers,
            timeout=30
        )
        data = res.json()
        log(f"  [VPS] 테마 저장: {data.get('saved', 0)}건")
    except Exception as e:
        log(f"  [VPS] push 오류: {e}")


def main():
    now = datetime.now(JST)
    log(f"=== 종목 테마 수집 시작: {now.strftime('%Y-%m-%d %H:%M JST')} ===")
    log(f"VPS: {'있음' if VPS_API_URL else '없음'}")

    # ★ 카부탄 접근 테스트
    log("카부탄 접근 테스트 중...")
    try:
        test_r = SESSION.get("https://kabutan.jp/stock/?code=9984", timeout=15)
        log(f"카부탄 HTTP: {test_r.status_code} / {len(test_r.text)}bytes")
        if test_r.status_code != 200:
            log("❌ 카부탄 접근 불가 — 종료")
            return
        test_themes = re.findall(r'/themes/\d+[^"]*">([^<]{2,20})</a>', test_r.text)
        log(f"9984 테마: {test_themes[:5]}")
    except Exception as e:
        log(f"❌ 카부탄 오류: {e} — 종료")
        return

    # 수집 대상: 닛케이225 + VPS 거래대금 상위
    target_codes = list(dict.fromkeys(NK225_CODES))  # 중복 제거
    top_codes = get_top_codes_from_vps()
    for c in top_codes:
        if c not in target_codes:
            target_codes.append(c)

    log(f"수집 대상: {len(target_codes)}종목")

    # 이미 수집된 종목 확인 (VPS)
    already_done = set()
    try:
        r = SESSION.get(f"{VPS_API_URL}/stock_master?limit=5000", timeout=10)
        if r.status_code == 200:
            items = r.json().get("items", [])
            for item in items:
                if item.get("theme_updated_at"):  # 이미 테마 수집됨
                    already_done.add(item["code"])
            log(f"  이미 수집된 종목: {len(already_done)}개")
    except Exception as e:
        log(f"  기존 수집 확인 실패: {e}")

    # 미수집 종목만 대상
    to_collect = [c for c in target_codes if c not in already_done]
    log(f"  신규 수집 대상: {len(to_collect)}종목")

    all_results = []
    success = 0
    empty = 0

    for i, code in enumerate(to_collect):
        # 카부탄 테마 수집
        themes = fetch_kabutan_themes(code)

        # 테마 없으면 민카부 시도
        if not themes:
            time.sleep(1)
            themes = fetch_minkabu_themes(code)

        if themes:
            log(f"  [{i+1}/{len(to_collect)}] {code}: {themes[:3]}")
            all_results.append({
                "code":   code,
                "themes": themes,
                "source": "kabutan",
            })
            success += 1
        else:
            empty += 1

        # 50개마다 중간 전송
        if len(all_results) >= 50:
            push_to_vps(all_results)
            all_results = []

        # 요청 간격 (봇차단 방지)
        time.sleep(2)

    # 남은 것 전송
    if all_results:
        push_to_vps(all_results)

    log(f"\n=== 완료 ===")
    log(f"  성공: {success}종목 / 테마 없음: {empty}종목")


if __name__ == "__main__":
    main()
