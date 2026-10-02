"""Economic calendar collector; import is side-effect free."""
from collector_common import push_json, event_identity


def main():
    import requests, json, re, os
    from datetime import datetime, timezone, timedelta
    from bs4 import BeautifulSoup
    
    VPS_URL = os.environ.get("VPS_NEWS_API_URL", "").rstrip("/")
    
    JST = timezone(timedelta(hours=9))
    now = datetime.now(JST)
    year = now.year
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "ja,en-US;q=0.9",
    }
    
    # ── nikkei225jp 스크래핑 (flag 클래스로 정확한 국가 판단) ──
    nk_events = []
    successful_sources = 0
    try:
        r = requests.get("https://nikkei225jp.com/schedule/", headers=headers, timeout=15)
        print(f"nikkei225jp: {r.status_code}")
        if r.status_code == 200:
            soup = BeautifulSoup(r.text, "html.parser")
            main_table = next((t for t in soup.find_all("table") if len(t.find_all("tr")) > 10), None)
            if main_table:
                successful_sources += 1
                current_date = None
                for row in main_table.find_all("tr"):
                    cells = row.find_all(["td","th"])
                    texts = [c.get_text(strip=True) for c in cells]
                    if not texts: continue
                    # 날짜 행
                    if len(texts) == 1 and re.match(r'\d+/\d+', texts[0]):
                        m = re.match(r'(\d+)/(\d+)', texts[0])
                        if m:
                            month,day=int(m.group(1)),int(m.group(2))
                            candidates=[]
                            for candidate_year in (year-1,year,year+1):
                                try:
                                    candidates.append(datetime(candidate_year,month,day,tzinfo=JST))
                                except ValueError:
                                    pass
                            current_date=min(candidates,key=lambda d:abs((d-now).days)).strftime('%Y-%m-%d')
                        continue
                    # 데이터 행
                    if len(texts) >= 6 and re.match(r'\d+:\d+', texts[0]) and current_date:
                        stars = texts[1].count("★")
                        if stars < 2: continue
    
                        # flag 클래스로 국가 판단
                        span = cells[2].find("span", class_=re.compile(r"flag1-")) if len(cells) > 2 else None
                        flag = ""
                        if span:
                            for cls in span.get("class", []):
                                if cls.startswith("flag1-"):
                                    flag = cls.replace("flag1-", "")
                                    break
    
                        # 포함 기준:
                        # JP/US → ★2 이상 전부
                        # EU(ECB) → ★5만 (ECB금리 등)
                        # 나머지(GB/DE/AU/CN 등) → 제외
                        if flag == "jp":
                            currency = "JPY"
                        elif flag == "us":
                            currency = "USD"
                        elif flag in ("eu",) and stars >= 5:
                            currency = "EUR"
                        else:
                            continue
    
                        nk_events.append({
                            "date": current_date, "time": texts[0],
                            "title": texts[2], "actual": texts[3],
                            "forecast": texts[4], "previous": texts[5],
                            "currency": currency, "stars": stars,
                        })
    
            usd = sum(1 for e in nk_events if e["currency"]=="USD")
            jpy = sum(1 for e in nk_events if e["currency"]=="JPY")
            eur = sum(1 for e in nk_events if e["currency"]=="EUR")
            print(f"파싱: {len(nk_events)}건 (JPY:{jpy} USD:{usd} EUR:{eur})")
            for ev in nk_events[:6]:
                print(f"  {ev['date']} {ev['time']} {ev['currency']} {ev['title'][:28]} | actual={ev['actual']}")
    
    except Exception as e:
        print(f"error: {e}")
        import traceback; traceback.print_exc()
    
    # ── ForexFactory JSON (미래 일정 보완) ──
    ff_items = []
    for url in ["https://nfs.faireconomy.media/ff_calendar_thisweek.json",
                "https://nfs.faireconomy.media/ff_calendar_nextweek.json"]:
        try:
            res = requests.get(url, headers={"User-Agent":"Mozilla/5.0"}, timeout=15)
            if res.status_code == 200:
                ff_items.extend(res.json())
                successful_sources += 1
        except: pass
    print(f"FF: {len(ff_items)}건")
    
    def parse_jst(s):
        try:
            dt = datetime.fromisoformat(s).astimezone(JST)
            return dt.strftime("%Y-%m-%d"), dt.strftime("%H:%M")
        except:
            raise ValueError("Invalid economic event timestamp")
    
    # nikkei225jp 기준 push
    push_items = []
    for ev in nk_events:
        push_items.append({
            "title": ev["title"], "currency": ev["currency"],
            "impact": "High" if ev["stars"] >= 4 else "Medium",
            "stars": ev["stars"],
            "date": ev["date"], "time": ev["time"],
            "forecast": ev["forecast"], "previous": ev["previous"],
            "actual": ev["actual"],
        })
    
    # FF에서 nikkei225jp에 없는 USD/JPY High/Medium 보완
    nk_keys = {event_identity(ev["date"], ev["time"], ev["currency"], ev["title"]) for ev in nk_events}
    for ev in ff_items:
        if ev.get("country") not in ("USD","JPY"): continue
        if ev.get("impact") not in ("High","Medium"): continue
        try:
            d, t = parse_jst(ev.get("date",""))
        except ValueError:
            continue
        if event_identity(d,t,ev.get("country",""),ev.get("title","")) not in nk_keys:
            push_items.append({
                "title": ev.get("title",""), "currency": ev.get("country",""),
                "impact": ev.get("impact",""), "date": d, "time": t,
                "forecast": ev.get("forecast"),
                "previous": ev.get("previous"),
                "actual": ev.get("actual"),
            })
    
    actual_cnt = sum(1 for p in push_items if p["actual"])
    print(f"총 push: {len(push_items)}건 (actual: {actual_cnt}건)")
    for p in push_items[:4]:
        print(f"  {p['date']} {p['time']} {p['currency']} {p['title'][:28]} | actual={p['actual']}")
    
    if push_items:
        print('Pushing calendar batch')
        result = push_json(VPS_URL,"/push/ff_events",{"items":push_items})
        print(f"VPS saved={result.get('saved',0)}")
    else:
        if not successful_sources:
            raise RuntimeError("All calendar sources failed")
        print("No calendar events")


if __name__ == "__main__":
    main()

