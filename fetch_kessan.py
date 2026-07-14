"""
fetch_kessan.py
===============
J-Quants /fins/announcement API로 결산예정 수집 → VPS push
GitHub Actions에서 매일 06:00 JST 실행

환경변수:
  JQUANTS_API_KEY  : J-Quants APIキー
  VPS_BASE_URL     : https://jpstocklive.com
  VPS_PUSH_SECRET  : push 인증 시크릿
"""

import os, sys, json, requests
from datetime import datetime, timedelta, timezone

JST = timezone(timedelta(hours=9))
JQUANTS_API_KEY = os.environ["JQUANTS_API_KEY"]
VPS_BASE_URL    = os.environ.get("VPS_BASE_URL", "https://jpstocklive.com")
VPS_PUSH_SECRET = os.environ.get("VPS_PUSH_SECRET", "")

JQ_HEADERS = {"x-api-key": JQUANTS_API_KEY}

def jst_now():
    return datetime.now(JST)

def fetch_announcement(date_str: str) -> list:
    """
    J-Quants /fins/announcement — 결산발표예정 조회
    date: YYYY-MM-DD
    """
    url = "https://api.jquants.com/v1/fins/announcement"
    try:
        res = requests.get(url, headers=JQ_HEADERS,
                           params={"date": date_str}, timeout=15)
        if res.status_code == 200:
            return res.json().get("announcement", [])
        elif res.status_code == 401:
            print(f"  ❌ J-Quants 인증 실패 (401) — API 키 확인")
        else:
            print(f"  ⚠️ J-Quants {date_str}: HTTP {res.status_code}")
    except Exception as e:
        print(f"  ❌ J-Quants 요청 오류 ({date_str}): {e}")
    return []

def parse_items(raw_list: list, date_str: str) -> list:
    """
    J-Quants announcement 응답 파싱
    필드: Code, CompanyName, FiscalYear, FiscalQuarter,
          Section (市場区分), AnnouncementDate, AnnouncementTime
    """
    result = []
    for r in raw_list:
        code = str(r.get("Code", "")).strip()
        if not code or len(code) < 4:
            continue
        code4 = code[:4]
        name  = r.get("CompanyName", "")
        fy    = r.get("FiscalYear", "")       # 例: 2026/03
        fq    = r.get("FiscalQuarter", "")    # 例: 3Q, Annual
        mkt   = r.get("Section", "")          # 例: プライム
        ann_date = r.get("AnnouncementDate", date_str)  # YYYY-MM-DD
        ann_time = r.get("AnnouncementTime", "")        # 例: 15:00, 本引後

        # 発表時間 정규화
        time_label = ""
        if ann_time:
            if "引前" in ann_time or "前場" in ann_time:
                time_label = "本引前"
            elif "引後" in ann_time or "後場" in ann_time:
                time_label = "本引後"
            elif ":" in ann_time:
                time_label = ann_time[:5]
            else:
                time_label = ann_time

        # 결산期 레이블
        period_label = ""
        if fq:
            q_map = {"1Q": "第1四半期", "2Q": "第2四半期",
                     "3Q": "第3四半期", "Annual": "通期", "4Q": "通期"}
            period_label = q_map.get(fq, fq)
        if fy:
            period_label = f"{fy.replace('/','.').replace('-','.')}期 {period_label}".strip()

        result.append({
            "code":         code4,
            "name":         name,
            "market":       mkt,
            "fiscal_period": period_label,
            "kessan_date":  ann_date,
            "kessan_time":  time_label,
            "source":       "jquants",
        })
    return result

def push_to_vps(items: list):
    """VPS /push/kessan エンドポイントへ送信"""
    url = f"{VPS_BASE_URL}/push/kessan"
    payload = {"items": items, "secret": VPS_PUSH_SECRET}
    try:
        res = requests.post(url, json=payload, timeout=30)
        if res.status_code == 200:
            j = res.json()
            print(f"  ✅ VPS push 완료: {j.get('saved', 0)}건 저장 / {j.get('total', 0)}건 수신")
        else:
            print(f"  ❌ VPS push 실패: HTTP {res.status_code} — {res.text[:200]}")
    except Exception as e:
        print(f"  ❌ VPS push 오류: {e}")
        sys.exit(1)

def main():
    now = jst_now()
    print(f"=== 결산예정 수집 시작 ({now.strftime('%Y-%m-%d %H:%M JST')}) ===")

    # 오늘 + 7일치 수집
    all_items = []
    seen = set()
    for delta in range(8):
        target = now + timedelta(days=delta)
        # 주말 스킵
        if target.weekday() >= 5:
            continue
        date_str = target.strftime("%Y-%m-%d")
        print(f"  [{delta+1}/8] {date_str} 조회 중...")
        raw = fetch_announcement(date_str)
        items = parse_items(raw, date_str)
        for item in items:
            key = f"{item['code']}_{item['kessan_date']}"
            if key not in seen:
                seen.add(key)
                all_items.append(item)
        print(f"    → {len(items)}건")

    print(f"\n총 {len(all_items)}건 수집 완료 → VPS push 중...")
    if all_items:
        push_to_vps(all_items)
    else:
        print("  ⚠️ 수집 데이터 없음 (장 휴일 or API 오류)")

    print("=== 완료 ===")

if __name__ == "__main__":
    main()
