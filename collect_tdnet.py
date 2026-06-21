"""
collect_tdnet.py
GitHub Actions에서 5분마다 실행 (평일 장중)
yanoshin API → VPS /push/tdnet 로 전송

v2 변경사항:
- 타임아웃 20→30초
- 재시도 2회
- rank3 즉시 감지 로그
- ETF/펀드 필터링 강화
"""
import os, time, requests
from datetime import datetime
from zoneinfo import ZoneInfo

JST = ZoneInfo("Asia/Tokyo")
VPS_API_URL = os.environ.get("VPS_NEWS_API_URL", "")
VPS_TOKEN   = os.environ.get("VPS_TOKEN", "")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0.0.0",
    "Accept": "application/json",
}

RANK3_KW = [
    "決算短信","業績予想の修正","業績修正","上方修正","下方修正",
    "TOB","公開買付","株式交換","合併","吸収合併","完全子会社","経営統合",
    "自己株式取得","自社株買い","増配","特別配当","配当予想修正","減配",
    "上場廃止","民事再生","破産","MSワラント","第三者割当",
    "株式分割","株式無償割当","新規上場","IPO","上場承認",
]

RANK2_KW = [
    "業務提携","資本提携","共同開発","戦略的提携",
    "子会社設立","合弁","増資","公募増資",
    "代表取締役","社長交代","役員変更","CEO",
    "工場建設","新工場","事業譲渡","事業売却",
    "リストラ","希望退職","人員削減",
    "大型受注","受注","契約締結","覚書",
    "株主優待","月次","売上高","営業利益",
]

# ETF/펀드 제외 키워드
ETF_KW = [
    "上場ETF","上場投信","ＥＴＦ","ＥＴＮ","投資信託",
    "日々の開示事項","ＭＡＸＩＳ","ブラックロック",
    "ｉシェアーズ","野村アセット","大和アセット",
    "コーポレート・ガバナンス","内部統制報告書","確認書",
    "有価証券届出書","臨時報告書の訂正","訂正有価証券",
]

def classify_rank(title: str, company: str = "") -> int:
    if any(kw in title for kw in ETF_KW): return 0  # 완전 제외
    if any(kw in company for kw in ["Ｅ－","Ｐ－"]): return 0
    if any(kw in title for kw in RANK3_KW): return 3
    if any(kw in title for kw in RANK2_KW): return 2
    return 1

def fetch_yanoshin(retry: int = 2) -> list:
    url = "https://webapi.yanoshin.jp/webapi/tdnet/list/today.json"
    for attempt in range(retry + 1):
        try:
            r = requests.get(url, headers=HEADERS, timeout=30)
            if r.status_code != 200:
                print(f"  [yanoshin] HTTP {r.status_code} (시도 {attempt+1})")
                if attempt < retry:
                    time.sleep(5)
                    continue
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
                if rank == 0:
                    continue  # ETF/제외 항목

                results.append({
                    "disclosure_id": f"yanoshin_{disc_id}",
                    "stock_code":    code,
                    "company_name":  company,
                    "title":         title,
                    "disclosed_at":  pubdate,
                    "rank":          rank,
                    "pdf_url":       pdf,
                })

            r3 = [x for x in results if x["rank"]==3]
            r2 = [x for x in results if x["rank"]==2]
            print(f"  [yanoshin] rank3: {len(r3)}건 / rank2: {len(r2)}건 / rank1: {len(results)-len(r3)-len(r2)}건")

            # rank3 즉시 표시
            for item in r3:
                print(f"  ★★★ {item['company_name']} [{item['stock_code']}] {item['title']}")

            return results

        except requests.exceptions.Timeout:
            print(f"  [yanoshin] 타임아웃 (시도 {attempt+1}/{retry+1})")
            if attempt < retry:
                time.sleep(5)
        except Exception as e:
            print(f"  [yanoshin] 오류: {e} (시도 {attempt+1}/{retry+1})")
            if attempt < retry:
                time.sleep(5)

    return []

def push_to_vps(items: list) -> None:
    if not items or not VPS_API_URL:
        print(f"  [VPS] 스킵 (items={len(items)}, url={'있음' if VPS_API_URL else '없음'})")
        return
    try:
        headers = {"Content-Type": "application/json"}
        if VPS_TOKEN:
            headers["X-Push-Token"] = VPS_TOKEN
        res = requests.post(
            f"{VPS_API_URL}/push/tdnet",
            json={"items": items},
            headers=headers,
            timeout=20
        )
        data = res.json()
        saved = data.get("saved", 0)
        print(f"  [VPS] {saved}/{len(items)}건 저장")
        if saved > 0:
            print(f"  ✅ 신규 공시 {saved}건 VPS 저장 완료")
    except Exception as e:
        print(f"  [VPS] push 오류: {e}")

def main():
    now = datetime.now(JST)
    print(f"=== TDnet 수집: {now.strftime('%Y-%m-%d %H:%M:%S')} JST ===")

    items = fetch_yanoshin()
    print(f"총 {len(items)}건 (rank0 제외)")
    push_to_vps(items)
    print("완료")

if __name__ == "__main__":
    main()
