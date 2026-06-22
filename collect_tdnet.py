# -*- coding: utf-8 -*-
"""
collect_tdnet.py — GitHub Actions에서 TDnet 공시 수집 → VPS push
"""
import os, sys, json, time, requests
from datetime import datetime, timezone, timedelta

JST = timezone(timedelta(hours=9))
VPS_URL = os.environ.get("VPS_NEWS_API_URL", os.environ.get("VPS_URL", "https://jpstocklive.com"))
TIMEOUT = 30

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json, */*",
    "Accept-Language": "ja,en;q=0.9",
}

# 중요도 분류
def _rank(title: str) -> int:
    t = title or ""
    if any(k in t for k in ["決算短信", "業績予想の修正", "配当予想の修正", "TOB", "MBO",
                              "公開買付", "自己株式取得", "合併", "分割", "上場廃止",
                              "民事再生", "破産", "第三者割当"]):
        return 4
    if any(k in t for k in ["業績", "配当", "株式", "取得", "売却", "子会社", "資本"]):
        return 3
    if any(k in t for k in ["契約", "提携", "受注", "開発", "新製品", "人事"]):
        return 2
    return 1

def fetch_tdnet():
    """yanoshin API에서 TDnet 수집"""
    items = []
    now_jst = datetime.now(JST)
    date_str = now_jst.strftime("%Y%m%d")

    # yanoshin API
    urls = [
        f"https://webapi.yanoshin.jp/webapi/tdnet/list/today.json?limit=100",
        f"https://webapi.yanoshin.jp/webapi/tdnet/list/{date_str}.json?limit=100",
    ]
    for url in urls:
        try:
            r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
            if r.status_code != 200:
                continue
            data = r.json()
            records = data if isinstance(data, list) else data.get("items", data.get("list", []))
            for rec in records:
                code = str(rec.get("company_code") or rec.get("code") or "").strip()[:4]
                title = rec.get("title") or rec.get("name") or ""
                disclosed = rec.get("disclosed_at") or rec.get("datetime") or ""
                disc_id = str(rec.get("id") or rec.get("disclosure_id") or "")
                url_link = rec.get("url") or rec.get("link") or ""
                company = rec.get("company_name") or rec.get("name_jp") or ""

                if not code or not title: continue
                rank = _rank(title)
                # 時間 추출 (HH:MM)
                time_str = ""
                if disclosed and len(disclosed) >= 16:
                    time_str = disclosed[11:16]

                items.append({
                    "disclosure_id": disc_id,
                    "code": code,
                    "company_name": company,
                    "title": title,
                    "rank": rank,
                    "disclosed_at": disclosed,
                    "time_str": time_str,
                    "url": url_link,
                })
            if items:
                print(f"✅ yanoshin: {len(items)}건")
                break
        except Exception as e:
            print(f"⚠️ {url}: {e}")
            continue

    return items

def push_to_vps(items):
    """VPS에 공시 데이터 push"""
    if not items:
        print("전송할 공시 없음")
        return
    try:
        r = requests.post(
            f"{VPS_URL}/push/tdnet",
            json={"items": items},
            timeout=30
        )
        result = r.json()
        print(f"✅ VPS push: {result.get('saved', 0)}건 저장 / {result.get('total', 0)}건 전달")
    except Exception as e:
        print(f"❌ VPS push 실패: {e}")
        sys.exit(1)

if __name__ == "__main__":
    print(f"[TDnet] 수집 시작 {datetime.now(JST).strftime('%Y-%m-%d %H:%M JST')}")
    items = fetch_tdnet()
    print(f"[TDnet] 수집: {len(items)}건")
    push_to_vps(items)
