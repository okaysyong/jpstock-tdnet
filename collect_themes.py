"""
collect_themes.py
GitHub Actions에서 실행 — 카부탄에서 종목 테마 수집 → VPS /push/themes
전종목 수집 (VPS stock_master 기준)
"""
import os, re, time, json, requests, sys
from datetime import datetime
from zoneinfo import ZoneInfo

JST = ZoneInfo("Asia/Tokyo")
VPS_API_URL = os.environ.get("VPS_NEWS_API_URL", "")
VPS_TOKEN   = os.environ.get("VPS_TOKEN", "")

def log(msg):
    print(msg, flush=True)

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ja-JP,ja;q=0.9,en-US;q=0.8",
    "Connection": "keep-alive",
})


def fetch_kabutan_themes(code: str) -> list:
    """카부탄 종목 페이지에서 投資テーマ 파싱"""
    url = f"https://kabutan.jp/stock/?code={code}"
    try:
        r = SESSION.get(url, timeout=15)
        if r.status_code != 200:
            return []
        html = r.text
        theme_links = re.findall(
            r'href="/themes/\?(?:theme|industry)=[^"]*"[^>]*>([^<]{2,20})<',
            html
        )
        seen = set()
        result = []
        skip = {"TOPIXコア30","TOPIX100","日経225","JPX日経400",
                "東証プライム","東証スタンダード","東証グロース",
                "情報・通信業","電気機器","機械","化学","銀行業"}
        for t in theme_links:
            t = t.strip()
            if t and t not in seen and t not in skip and 2 <= len(t) <= 20:
                seen.add(t)
                result.append(t)
        return result[:10]
    except Exception as e:
        return []


def get_all_codes_from_vps() -> list:
    """VPS stock_master에서 전종목 코드 가져오기"""
    try:
        r = SESSION.get(f"{VPS_API_URL}/stock_master", timeout=30)
        if r.status_code == 200:
            items = r.json().get("items", [])
            codes = [str(item["code"])[:4] for item in items if item.get("code")]
            log(f"  [VPS] 전종목: {len(codes)}개")
            return codes
    except Exception as e:
        log(f"  [VPS] stock_master 조회 실패: {e}")
    return []


def get_already_done_from_vps() -> set:
    """VPS stock_themes에서 이미 수집된 종목 확인"""
    try:
        r = SESSION.get(f"{VPS_API_URL}/themes/collected", timeout=15)
        if r.status_code == 200:
            codes = set(r.json().get("codes", []))
            log(f"  [VPS] 이미 수집된 종목: {len(codes)}개")
            return codes
    except Exception as e:
        log(f"  기존 수집 확인 실패: {e}")
    return set()


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

    # 카부탄 접근 테스트
    log("카부탄 접근 테스트 중...")
    try:
        test_r = SESSION.get("https://kabutan.jp/stock/?code=9984", timeout=15)
        log(f"카부탄 HTTP: {test_r.status_code} / {len(test_r.text)}bytes")
        if test_r.status_code != 200:
            log("❌ 카부탄 접근 불가 — 종료")
            return
    except Exception as e:
        log(f"❌ 카부탄 오류: {e} — 종료")
        return

    # 전종목 코드 가져오기 (VPS stock_master)
    all_codes = get_all_codes_from_vps()
    if not all_codes:
        log("❌ 종목 코드 없음 — 종료")
        return

    # 전종목 수집 (변경/신규 모두 업데이트)
    to_collect = all_codes
    log(f"수집 대상: {len(to_collect)}종목 (전체 수집)")

    all_results = []
    success = 0
    empty = 0

    for i, code in enumerate(to_collect):
        themes = fetch_kabutan_themes(code)

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
