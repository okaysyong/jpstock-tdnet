"""
collect_news.py
GitHub Actions에서 실행 — NHK/Reuters/Bloomberg RSS 수집 → VPS push
평일/주말 관계없이 5분마다 실행

변경사항:
- yahoo_fin/yahoo_it/yahoo_biz 제거 (자동차/생활 잡뉴스 주 소스)
- reuters_jp/bloomberg_jp 추가 (GitHub Actions IP는 차단 안됨)
- EXCLUDE_KW 대폭 강화 (자동차/생활/사건사고 등)
- HIGH_KW 강화 (일본주식 직접 영향 키워드)
"""
import os, re, time, hashlib, json
from datetime import datetime, timezone, timedelta
import requests
import xml.etree.ElementTree as ET

VPS_API_URL = os.environ.get("VPS_NEWS_API_URL", "")

JST = timezone(timedelta(hours=9))

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
}

RSS_FEEDS = [
    # NHK 경제/금융 특화
    ("nhk_biz",    "https://www.nhk.or.jp/rss/news/cat5.xml"),  # 경제/기업
    ("nhk_world",  "https://www.nhk.or.jp/rss/news/cat4.xml"),  # 국제경제
    ("nhk_eco",    "https://www.nhk.or.jp/rss/news/cat6.xml"),  # 과학/기술
    # 금융 전문 (GitHub Actions IP는 차단 안됨)
    ("reuters_jp", "https://feeds.reuters.com/reuters/JPBusinessNews"),
    ("reuters_en", "https://feeds.reuters.com/reuters/businessNews"),
    ("bloomberg",  "https://www.bloomberg.co.jp/feeds/bpol/news"),
    # Yahoo Finance JP (비즈니스 카테고리 — 잡뉴스 많지만 필터링 적용)
    ("yahoo_fin",  "https://news.yahoo.co.jp/rss/categories/business.xml"),
]

# ★ 제외 키워드 (주식 무관 완전 차단)
EXCLUDE_KW = [
    # 스포츠
    "サッカー","野球","バスケ","テニス","ゴルフ","ラグビー","五輪",
    "オリンピック","W杯","ワールドカップ","高校野球","Jリーグ","プロ野球",
    "カーリング","スケート","水泳","体操","柔道","相撲","レスリング",
    "マラソン","陸上","バレー","バドミントン","卓球","ボクシング","スポーツ",
    "選手権","リーグ戦","監督","コーチ","ホームラン","打点","登板",
    "大谷翔平","佐々木朗希","ドジャース","ヤンキース",
    # 연예/문화
    "芸能","アイドル","歌手","俳優","映画","ドラマ","コンサート",
    "音楽","エンタメ","バラエティ","漫画","アニメ","タレント",
    # 자동차/이동수단 (주식 무관 기사)
    "ベストカー","MotorFan","carview","乗りものニュース","Auto Messe",
    "ノートオーラ","アルファード","ハイラックス","N-BOX","ロードスター",
    "エアロ","カスタム","バイク","二輪","アウトバーン","レンタカー",
    "夜行バス","航空機","エアフォース","エティハド","Aviation Wire",
    # 생활/취미
    "グルメ","食べ歩き","観光","旅行","温泉","スイーツ","ビリヤニ",
    "ラーメン","そば","うどん","料理","レシピ","カフェ",
    "日焼け","スキンケア","美容","ダイエット","健康食品","天然パーマ",
    "時計","スマホ","Android","Wi-Fi","ガジェット",
    "ドローン","測量","3D","VR","ゲーム","キャラ",
    # 사건사고 (주식 무관)
    "交通事故","火災","逮捕","容疑者","殺人","詐欺被害","窃盗","強盗",
    "行方不明","死亡事故","遺体","列車衝突","落下","衝突事故",
    "人身事故","重傷","軽傷","けが人","冷凍庫",
    # 황실/정치 (경제 무관)
    "天皇","皇后","皇室","陛下","皇太子","皇族","両陛下",
    "慰霊","追悼","記念式典","表敬訪問","植樹",
    "立民","公明","維新","参院","衆院","委員会",
    "沖縄","糸満","博物館","ハラスメント","弁護士相談",
    # 잡지/미디어 소스명 (제목에 포함된 경우)
    "ダイヤモンド・オンライン","東洋経済オンライン","プレジデント",
    "Merkmal","LIMO","Finasee","WEB CARTOP","MotorFan","carview",
    "ベストカーWeb","乗りものニュース","Auto Messe","Aviation Wire",
    "バイクのニュース","ライフハッカー","VAGUE",
    # 취업/교육
    "売り手市場","就職","ハロワ","ハローワーク","採用","転職","求人",
    "奨学金","入試","受験","大学院",
    # 기타 무관
    "ナビスコ","ギフティ","フリマ","メルカリ","ヤフオク",
    "クレーンゲーム","ガチャ","パチンコ","競馬","宝くじ",
]

# ★ 고중요도 키워드 (일본주식 직접 영향)
HIGH_KW = [
    # 금융정책
    "日銀","BOJ","金利","FOMC","FRB","利上げ","利下げ","量的緩和",
    "政策金利","マイナス金利","為替介入",
    # 경제지표
    "GDP","CPI","PCE","雇用統計","インフレ","デフレ","景気後退",
    "貿易収支","経常収支","消費者物価",
    # 기업 이벤트
    "決算","業績修正","上方修正","下方修正","TOB","買収","合併",
    "上場廃止","破産","民事再生","増資","自社株買い","配当修正",
    "社長交代","CEO","リストラ","希望退職","早期退職",
    # 시장
    "日経平均","TOPIX","円高","円安","円相場","ドル円","株価急落","急騰",
    "半導体","AI投資","データセンター","関税","輸出規制","制裁",
    "原油","WTI","天然ガス","金価格","銅価格",
    # 지정학
    "ホルムズ","台湾有事","地政学","安全保障","防衛費",
]

# ★ 중요도 키워드 (2차)
MEDIUM_KW = [
    "株式","株価","上場","IPO","投資","ファンド","ETF",
    "売上","利益","増収","増益","黒字","赤字",
    "受注","契約","提携","新製品","特許","FDA承認",
    "ソフトバンク","トヨタ","ソニー","任天堂","東京エレクトロン",
    "ファーストリテイリング","三菱UFJ","三井住友","みずほ",
    "輸出","輸入","需要","供給","市況","在庫",
]


def _uid(source: str, title: str) -> str:
    return hashlib.md5(f"{source}:{title}".encode()).hexdigest()[:16]


def _parse_rss(xml_text: str, source: str) -> list:
    items = []
    try:
        xml_text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', xml_text)
        root = ET.fromstring(xml_text)
        ch = root.find("channel")
        entries = ch.findall("item") if ch is not None else root.findall(".//item")

        for entry in entries:
            def _t(tag):
                el = entry.find(tag)
                return el.text.strip() if el is not None and el.text else ""

            title = _t("title")
            url   = _t("link") or _t("guid")
            pub   = _t("pubDate") or ""

            if not title or not url:
                continue

            pub_dt = None
            for fmt in [
                "%a, %d %b %Y %H:%M:%S %z",
                "%a, %d %b %Y %H:%M:%S %Z",
                "%Y-%m-%dT%H:%M:%S%z",
                "%Y-%m-%dT%H:%M:%SZ",
            ]:
                try:
                    pub_dt = datetime.strptime(pub.strip(), fmt)
                    break
                except ValueError:
                    continue

            if pub_dt is None:
                pub_dt = datetime.now(timezone.utc)

            pub_jst = pub_dt.astimezone(JST)
            pub_str = pub_jst.strftime("%Y-%m-%d %H:%M:%S")

            age_min = int((datetime.now(timezone.utc) - pub_dt.astimezone(timezone.utc)).total_seconds() / 60)
            if age_min > 1440:  # 24시간 이상 오래된 뉴스 제외
                continue

            items.append({
                "uid":          _uid(source, title),
                "title":        title,
                "summary":      "",
                "url":          url,
                "source":       source,
                "published_at": pub_str,
                "age_min":      age_min,
                "stocks":       "",
                "sectors":      "",
                "score":        2,
            })
    except Exception as e:
        print(f"  [{source}] 파싱 오류: {e}")

    return items


def fetch_rss(source: str, url: str) -> list:
    try:
        res = requests.get(url, headers=HEADERS, timeout=15)
        if res.status_code != 200:
            print(f"  [{source}] HTTP {res.status_code}")
            return []
        items = _parse_rss(res.text, source)

        filtered = []
        for item in items:
            title = item.get("title", "")

            # 제외 키워드 체크
            if any(kw in title for kw in EXCLUDE_KW):
                continue

            # 중요도 계산
            if any(kw in title for kw in HIGH_KW):
                score = 4
            elif any(kw in title for kw in MEDIUM_KW):
                score = 3
            else:
                score = 2

            item["score"] = score
            filtered.append(item)

        print(f"  [{source}] {len(filtered)}건 (원본 {len(items)}건)")
        return filtered
    except Exception as e:
        print(f"  [{source}] 오류: {e}")
        return []


def push_to_vps(items: list) -> dict:
    if not items:
        print("  전송할 뉴스 없음")
        return {"saved": 0}
    try:
        res = requests.post(
            f"{VPS_API_URL}/push/news",
            json={"items": items},
            timeout=30,
        )
        return res.json()
    except Exception as e:
        print(f"  VPS push 오류: {e}")
        return {"saved": 0}


def main():
    now = datetime.now(JST)
    print(f"=== 뉴스 수집 시작: {now.strftime('%Y-%m-%d %H:%M:%S')} JST ===")

    all_items = []
    seen_uids = set()

    for source, url in RSS_FEEDS:
        items = fetch_rss(source, url)
        for item in items:
            if item["uid"] not in seen_uids:
                seen_uids.add(item["uid"])
                all_items.append(item)
        time.sleep(1)

    # score 높은 것 우선 정렬
    all_items.sort(key=lambda x: (-x.get("score", 2), x.get("age_min", 9999)))

    print(f"\n총 {len(all_items)}건 수집 (중복 제거)")
    print(f"  HIGH(score=4): {len([x for x in all_items if x['score']==4])}건")
    print(f"  MED (score=3): {len([x for x in all_items if x['score']==3])}건")
    print(f"  LOW (score=2): {len([x for x in all_items if x['score']==2])}건")

    result = push_to_vps(all_items)
    saved = result.get("saved", 0)
    print(f"VPS 저장: {saved}건")
    print("완료")


if __name__ == "__main__":
    main()
