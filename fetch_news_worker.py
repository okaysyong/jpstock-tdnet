import requests, feedparser, json, time, hashlib, os
from datetime import datetime, timezone, timedelta
from news_collection_policy import (
    clean_text, news_uid, normalize_score, publication_time, relevance,
    PRIMARY_FEEDS, article_url, publisher_name,
)

JST = timezone(timedelta(hours=9))
VPS_URL = os.environ.get("VPS_URL", "https://jpstocklive.com")
VPS_TOKEN = os.environ.get("VPS_TOKEN", "")

RSS_FEEDS = [
    ("nhk_eco",    "https://www.nhk.or.jp/rss/news/cat5.xml"),
    ("cnbc_asia",  "https://www.cnbc.com/id/20910258/device/rss/rss.html"),
    ("cnbc_world", "https://www.cnbc.com/id/100003114/device/rss/rss.html"),
    ("cnbc_fin",   "https://www.cnbc.com/id/10000664/device/rss/rss.html"),
    ("yahoo_biz",  "https://news.yahoo.co.jp/rss/categories/business.xml"),
]
RSS_FEEDS.extend(PRIMARY_FEEDS)

EXCLUDE_KW = [
    "サッカー","野球","バスケ","テニス","ゴルフ","ラグビー","五輪",
    "オリンピック","W杯","ワールドカップ","高校野球","Jリーグ","プロ野球",
    "大リーグ","MLB","NFL","NBA","ドジャース","ヤンキース",
    "大谷","佐々木朗","鈴木誠","松井裕","ホームラン","打点","登板",
    "大相撲","力士","横綱","金メダル","銀メダル","マラソン","駅伝",
    "芸能","アイドル","歌手","俳優","映画","ドラマ","コンサート",
    "音楽","エンタメ","バラエティ","漫画","アニメ","タレント",
    "台風","大雨","洪水","土砂","ひょう","雷","竜巻","熱中症","梅雨",
    "交通事故","火災","逮捕","容疑者","殺人","詐欺被害","強盗",
    "行方不明","死亡事故","遺体","列車衝突","落下","衝突事故",
    "表敬訪問","記念式典","慰霊","追悼",
    "天皇","皇后","皇室","陛下","皇太子","皇族","両陛下",
    "グルメ","食べ歩き","観光","旅行","温泉","スイーツ","ビリヤニ",
    "日焼け","スキンケア","美容","ダイエット",
    "MotorFan","carview","ベストカーWeb","乗りものニュース",
    "Auto Messe","Aviation Wire","バイクのニュース",
    "定時制","通信制","フリマ","メルカリ","相続","口座凍結",
    "パチンコ","競馬","宝くじ","ハローワーク",
]

HIGH_KW = [
    "日銀","BOJ","金利","FOMC","FRB","利上げ","利下げ",
    "GDP","CPI","PCE","雇用統計","インフレ","景気後退",
    "決算","業績修正","上方修正","下方修正","TOB","買収","合併",
    "上場廃止","破産","増資","自社株買い","配当修正",
    "日経平均","TOPIX","円高","円安","円相場","ドル円",
    "半導体","AI投資","関税","輸出規制","制裁",
    "原油","WTI","天然ガス","ホルムズ","台湾",
    "Bank of Japan","interest rate","Federal Reserve","Fed rate",
    "rate hike","rate cut","inflation","CPI","jobs report",
    "Nikkei","yen","USD/JPY","semiconductor","chip","tariff",
    "oil price","crude","OPEC","Taiwan","earnings","GDP",
    "SoftBank","Toyota","Sony","Nintendo","Tokyo Electron",
    "Japan stock","Japanese yen","sell-off","rally",
]

MEDIUM_KW = [
    "株式","株価","上場","IPO","投資","ファンド",
    "売上","利益","増収","増益","黒字","赤字",
    "受注","契約","提携","新製品","特許",
    "ソフトバンク","トヨタ","ソニー","任天堂","東京エレクトロン",
    "三菱UFJ","三井住友","みずほ","ファーストリテイリング",
    "輸出","輸入","需要","供給","市況",
    "イラン","ウクライナ","ロシア","EU規制","対中",
    "Japan stock","Japanese yen","Nikkei","Bank of Japan",
    "yen intervention","chip stocks","AI stocks",
    "Fed minutes","FOMC minutes","treasury yield",
    "oil supply","crude oil","OPEC cut",
]

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/rss+xml, application/xml, text/xml, */*",
    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
}

all_news = []
seen_uids = set()
successful_sources = 0

for source, url in RSS_FEEDS:
    try:
        r = requests.get(url, timeout=12, headers=headers)
        if r.status_code != 200:
            print(f"SKIP {source}: {r.status_code}")
            continue
        feed = feedparser.parse(r.text)
        if feed.bozo and not feed.entries:
            raise ValueError('RSS response could not be parsed')
        successful_sources += 1
        count = 0
        for entry in feed.entries[:30]:
            title = (entry.get("title") or "").strip()
            if not title:
                continue
            # A generic market word is not a Japanese-equity connection.
            link = article_url(entry.get('link'))
            summary = clean_text(entry.get('summary'))[:300]
            reason, stocks = relevance(title, source_url=link, summary=summary)
            if reason == "no_verified_japan_equity_link":
                continue
            if any(kw in title for kw in HIGH_KW):
                score = 4
            elif any(kw in title for kw in MEDIUM_KW):
                score = 3
            else:
                score = 2
            published_dt = publication_time(entry)
            if published_dt is None:
                continue
            published = published_dt.astimezone(JST).strftime("%Y-%m-%d %H:%M:%S")
            uid = news_uid(link, title, published)
            if uid == "news_":
                continue
            if uid in seen_uids:
                continue
            seen_uids.add(uid)
            all_news.append({
                "uid":          uid,
                "title":        title,
                "summary":      summary,
                "url":          link,
                "source":       publisher_name(entry, source),
                "published_at": published,
                "stocks":       stocks,
                "score":        normalize_score(score),
            })
            count += 1
        print(f"OK {source}: {count}")
    except Exception as e:
        print(f"ERR {source}: {e}")
    time.sleep(1)

all_news.sort(key=lambda x: -x.get("score", 2))

print(f"Total: {len(all_news)}")
print(f"  HIGH(1.0): {len([x for x in all_news if x['score']==1.0])}")
print(f"  MED (.75): {len([x for x in all_news if x['score']==0.75])}")
print(f"  LOW (.5): {len([x for x in all_news if x['score']==0.5])}")

if not all_news:
    if not successful_sources:
        raise RuntimeError('All RSS sources failed')
    print("No news")
    exit(0)

from collector_common import push_json
result = push_json(VPS_URL,'/push/news',{'items':all_news},timeout=30)
print(f"VPS saved={result.get('saved',0)} duplicate={result.get('duplicates',0)}")
