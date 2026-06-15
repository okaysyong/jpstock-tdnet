"""
collect_tdnet.py
yanoshin API에서 TDnet 전체 공시 수집 → VPS push
GitHub Actions에서 5분마다 실행
"""
import os, re, time, json, hashlib, requests
from datetime import datetime
from zoneinfo import ZoneInfo

JST = ZoneInfo("Asia/Tokyo")
VPS_API_URL = os.environ.get("VPS_NEWS_API_URL", "")
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/html, */*",
    "Accept-Language": "ja,en-US;q=0.9",
}

# ── 중요도 분류 키워드 ──────────────────────────
RANK3_KW = [
    # 결산/업적
    "決算短信", "業績予想の修正", "業績修正", "四半期決算",
    "通期業績", "売上高修正", "営業利益修正", "純利益修正",
    # M&A / TOB
    "TOB", "公開買付", "株式交換", "合併", "吸収合併",
    "子会社化", "買収", "経営統合",
    # 자사주/배당
    "自己株式取得", "自社株買い", "増配", "特別配当",
    # 기타 긴급
    "上場廃止", "民事再生", "破産", "債務超過",
    "MSワラント", "第三者割当",
]
RANK2_KW = [
    "業務提携", "資本提携", "増資", "公募増資",
    "株式分割", "株式併合",
    "代表取締役", "社長交代", "役員変更",
    "月次", "月次売上", "配当予想",
    "新規上場", "MSCI",
]

def classify_rank(title: str, category: str = "") -> int:
    for kw in RANK3_KW:
        if kw in title:
            return 3
    for kw in RANK2_KW:
        if kw in title:
            return 2
    if category in ("today_market", "today_after"):
        return 2
    return 1

def fetch_yanoshin() -> list:
    """
    yanoshin WebAPI로 오늘 전체 TDnet 공시 수집
    """
    url = "https://webapi.yanoshin.jp/webapi/tdnet/list/today.json"
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        if r.status_code != 200:
            print(f"  [yanoshin] HTTP {r.status_code}")
            return []
        data = r.json()
        items_raw = data.get("items", [])
        print(f"  [yanoshin] 전체 공시: {len(items_raw)}건")

        results = []
        seen = set()
        now_str = datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S")

        for item in items_raw:
            disc_id = str(item.get("id", ""))
            if not disc_id or disc_id in seen:
                continue
            seen.add(disc_id)

            code  = str(item.get("code", "")).strip()
            name  = str(item.get("company_name", "")).strip()
            title = str(item.get("title", "")).strip()
            pdf   = str(item.get("document_url", "")).strip()

            # 시각
            dt_str = item.get("time", "") or item.get("pubdate", "") or now_str
            try:
                if "T" in dt_str:
                    from datetime import datetime as _dt
                    disclosed_at = _dt.fromisoformat(dt_str).astimezone(JST).strftime("%Y-%m-%d %H:%M:%S")
                else:
                    disclosed_at = dt_str[:19] if len(dt_str) >= 19 else now_str
            except Exception:
                disclosed_at = now_str

            rank = classify_rank(title)

            results.append({
                "disclosure_id": f"yanoshin_{disc_id}",
                "stock_code":    code,
                "company_name":  name,
                "title":         title,
                "disclosed_at":  disclosed_at,
                "rank":          rank,
                "pdf_url":       pdf,
            })

        # 중요도별 통계
        r3 = [x for x in results if x["rank"] == 3]
        r2 = [x for x in results if x["rank"] == 2]
        print(f"  [yanoshin] rank3(긴급): {len(r3)}건 / rank2(주목): {len(r2)}건")
        for x in r3[:5]:
            print(f"    ★★★ {x['stock_code']} {x['company_name']}: {x['title'][:40]}")

        return results

    except Exception as e:
        print(f"  [yanoshin] 오류: {e}")
        return []


def fetch_tdnet_direct() -> list:
    """
    yanoshin 실패 시 TDnet 직접 HTML 폴백
    """
    from datetime import datetime as _dt
    today = _dt.now(JST).strftime("%Y%m%d")
    url = f"https://www.release.tdnet.info/inbs/I_list_001_{today}.html"
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        if r.status_code != 200:
            return []
        html = r.text
        items = []
        rows = re.findall(
            r'<tr[^>]*>.*?(\d{2}:\d{2}).*?stock\?code=(\d{4}[A-Z]?).*?>([^<]+)</a>.*?<td[^>]*>([^<]+)</td>',
            html, re.DOTALL
        )
        now_date = _dt.now(JST).strftime("%Y-%m-%d")
        for time_str, code, name, title in rows[:100]:
            title = title.strip()
            name  = name.strip()
            disc_id = hashlib.md5(f"tdnet_{code}_{today}_{title}".encode()).hexdigest()[:16]
            items.append({
                "disclosure_id": disc_id,
                "stock_code":    code,
                "company_name":  name,
                "title":         title,
                "disclosed_at":  f"{now_date} {time_str}:00",
                "rank":          classify_rank(title),
                "pdf_url":       "",
            })
        print(f"  [tdnet_direct] {len(items)}건")
        return items
    except Exception as e:
        print(f"  [tdnet_direct] 오류: {e}")
        return []


def push_to_vps(items: list) -> None:
    if not items:
        return
    try:
        res = requests.post(
            f"{VPS_API_URL}/push/tdnet",
            json={"items": items},
            timeout=20
        )
        data = res.json()
        print(f"  VPS: {data.get('saved',0)}/{len(items)}건 저장")
    except Exception as e:
        print(f"  VPS push 오류: {e}")


def main():
    now_jst = datetime.now(JST)
    print(f"=== TDnet 수집 시작: {now_jst.strftime('%Y-%m-%d %H:%M:%S')} JST ===")

    # 1순위: yanoshin API
    items = fetch_yanoshin()

    # 폴백: TDnet 직접
    if not items:
        print("  yanoshin 실패 → TDnet 직접 시도")
        items = fetch_tdnet_direct()

    print(f"\n총 {len(items)}건 수집")
    push_to_vps(items)
    print("완료")


if __name__ == "__main__":
    main()
