"""
collect_tdnet.py
GitHub Actions에서 5분마다 실행
yanoshin API → VPS /push/tdnet 로 전송 (백업 수집원)
VPS가 직접 수집 실패 시 이 경로로 데이터 보완
"""
import os, time, requests
from datetime import datetime
from zoneinfo import ZoneInfo

JST = ZoneInfo("Asia/Tokyo")
VPS_API_URL = os.environ.get("VPS_NEWS_API_URL", "")
VPS_TOKEN   = os.environ.get("VPS_TOKEN", "")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0",
    "Accept": "application/json",
}

RANK3_KW = [
    "決算短信","業績予想の修正","業績修正","上方修正","下方修正",
    "TOB","公開買付","株式交換","合併","吸収合併","完全子会社","経営統合",
    "自己株式取得","自社株買い","増配","特別配当","配当予想修正",
    "上場廃止","民事再生","破産","MSワラント","第三者割当",
]
RANK2_KW = [
    "業務提携","資本提携","株式分割","増資","公募増資",
    "代表取締役","社長交代","月次","受注","契約締結",
]
ETF_KW = [
    "上場ETF","上場投信","ＥＴＦ","ＥＴＮ","投資信託",
    "日々の開示事項","ＭＡＸＩＳ","ブラックロック",
]

def classify_rank(title: str, company: str = "") -> int:
    if any(kw in title for kw in ETF_KW): return 1
    if any(kw in company for kw in ["Ｅ－","Ｐ－"]): return 1
    if any(kw in title for kw in RANK3_KW): return 3
    if any(kw in title for kw in RANK2_KW): return 2
    return 1

def fetch_yanoshin() -> list:
    url = "https://webapi.yanoshin.jp/webapi/tdnet/list/today.json"
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        if r.status_code != 200:
            print(f"  [yanoshin] HTTP {r.status_code}")
            return []
        data = r.json()
        raw = data.get("items", [])
        print(f"  [yanoshin] {len(raw)}건 수신")

        results = []
        seen = set()
        now_str = datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S")

        for it in raw:
            td = it.get("Tdnet", it)
            disc_id = str(td.get("id",""))
            if not disc_id or disc_id in seen:
                continue
            seen.add(disc_id)

            code    = str(td.get("company_code","")).strip()
            company = str(td.get("company_name","")).strip()
            title   = str(td.get("title","")).strip()
            pdf     = str(td.get("document_url","")).strip()
            pubdate = td.get("pubdate","") or now_str

            rank = classify_rank(title, company)

            results.append({
                "disclosure_id": f"yanoshin_{disc_id}",
                "stock_code":    code,
                "company_name":  company,
                "title":         title,
                "disclosed_at":  pubdate,
                "rank":          rank,
                "pdf_url":       pdf,
            })

        r3 = sum(1 for x in results if x["rank"]==3)
        r2 = sum(1 for x in results if x["rank"]==2)
        print(f"  [yanoshin] rank3: {r3}건 / rank2: {r2}건")
        return results

    except Exception as e:
        print(f"  [yanoshin] 오류: {e}")
        return []

def push_to_vps(items: list) -> None:
    if not items or not VPS_API_URL:
        return
    try:
        headers = {}
        if VPS_TOKEN:
            headers["X-Push-Token"] = VPS_TOKEN
        res = requests.post(
            f"{VPS_API_URL}/push/tdnet",
            json={"items": items},
            headers=headers,
            timeout=20
        )
        data = res.json()
        print(f"  VPS: {data.get('saved',0)}/{len(items)}건 저장")
    except Exception as e:
        print(f"  VPS push 오류: {e}")

def main():
    now = datetime.now(JST)
    print(f"=== TDnet 백업 수집: {now.strftime('%Y-%m-%d %H:%M:%S')} JST ===")

    items = fetch_yanoshin()
    print(f"총 {len(items)}건")
    push_to_vps(items)
    print("완료")

if __name__ == "__main__":
    main()
