"""Pure news collection checks. Relevance is not evidence of a price cause.

This file is mirrored in the VPS backend. Keep the copies byte-identical.
"""
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
import hashlib
import html
import math
import re
import unicodedata
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

JST = timezone(timedelta(hours=9))

# Curated unambiguous aliases; a missing company is withheld, never guessed.
ISSUERS = {
    "7203": ("トヨタ", "Toyota"), "6758": ("ソニー", "Sony"),
    "9984": ("ソフトバンクグループ", "SoftBank Group", "ソフトバンクG"),
    "9434": ("ソフトバンク株式会社", "SoftBank Corp"), "7974": ("任天堂", "Nintendo"),
    "8035": ("東京エレクトロン", "Tokyo Electron"),
    "6857": ("アドバンテスト", "Advantest"),
    "7735": ("SCREEN", "スクリーンHD"), "6920": ("レーザーテック", "Lasertec"),
    "4063": ("信越化学", "Shin-Etsu Chemical"), "3436": ("SUMCO", "サムコ"),
    "6861": ("キーエンス", "Keyence"), "6762": ("TDK",),
    "7741": ("HOYA",), "6501": ("日立製作所", "Hitachi"),
    "6503": ("三菱電機", "Mitsubishi Electric"), "6701": ("NEC", "日本電気"),
    "6702": ("富士通", "Fujitsu"), "6954": ("ファナック", "Fanuc"),
    "6367": ("ダイキン", "Daikin"), "6981": ("村田製作所", "Murata Manufacturing"),
    "8306": ("三菱UFJ", "MUFG"), "8316": ("三井住友FG", "SMFG"),
    "8411": ("みずほFG", "みずほフィナンシャル", "Mizuho Financial"),
    "8058": ("三菱商事", "Mitsubishi Corp"), "8031": ("三井物産", "Mitsui & Co"),
    "8001": ("伊藤忠", "Itochu"), "8002": ("丸紅", "Marubeni"),
    "7267": ("ホンダ", "本田技研", "Honda"), "7269": ("スズキ", "Suzuki"),
    "7201": ("日産自動車", "日産", "Nissan"),
    "9983": ("ファーストリテイリング", "Fast Retailing"),
    "6098": ("リクルートHD", "リクルートホールディングス", "Recruit Holdings"),
    "9432": ("NTT",), "9433": ("KDDI",), "4755": ("楽天グループ", "Rakuten"),
    "4385": ("メルカリ", "Mercari"), "4661": ("オリエンタルランド", "Oriental Land"),
    "7832": ("バンダイナムコ", "Bandai Namco"), "9697": ("カプコン", "Capcom"),
    "4519": ("中外製薬", "Chugai"), "4502": ("武田薬品", "Takeda"),
    "4568": ("第一三共", "Daiichi Sankyo"), "4503": ("アステラス", "Astellas"),
    "7011": ("三菱重工", "Mitsubishi Heavy"), "7012": ("川崎重工", "Kawasaki Heavy"),
    "7013": ("IHI",), "1605": ("INPEX",), "5020": ("ENEOS",),
    "2914": ("日本たばこ", "Japan Tobacco"), "8267": ("イオン", "Aeon"),
    "3382": ("セブン&アイ", "セブン＆アイ", "Seven & i"),
    "4704": ("トレンドマイクロ", "Trend Micro"),
}

MATERIAL_EVENTS = (
    "決算", "業績", "上方修正", "下方修正", "増収", "減収", "増益", "減益",
    "営業利益", "純利益", "売上高", "赤字", "黒字", "配当", "自社株", "自己株式",
    "株式分割", "増資", "TOB", "MBO", "買収", "合併", "子会社化", "提携",
    "受注", "契約", "売却", "事業譲渡", "工場", "生産停止", "操業停止", "設備投資",
    "承認取得", "製造販売承認", "臨床試験", "リコール", "上場廃止", "破産",
    "earnings", "guidance", "revenue", "profit", "dividend", "buyback", "acquisition",
    "acquire", "merger", "takeover", "contract", "partnership", "factory", "production",
    "recall", "clinical trial", "regulatory approval", "stock split", "delist",
)


def clean_text(value):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", str(value or "")))).strip()


def _match(text, phrase):
    # English names must not match longer words (Sony != Sonyville).
    if re.fullmatch(r"[\x00-\x7f]+", phrase):
        if phrase == "SCREEN":
            return re.search(r"(?<![A-Za-z0-9])SCREEN(?![A-Za-z0-9])", text) is not None
        return re.search(r"(?<![a-z0-9])" + re.escape(phrase.casefold()) + r"(?![a-z0-9])",
                         text.casefold()) is not None
    return phrase in text


def relevance(title, aliases=None):
    """Return (reason, codes); no probability, cause, or inferred sector claims."""
    title = unicodedata.normalize("NFKC", clean_text(title))
    registry = dict(ISSUERS)
    for code, names in (aliases or {}).items():
        if re.fullmatch(r"[0-9A-Z]{4,5}", str(code)):
            if isinstance(names, str):
                names = [names]
            # Never admit a short ambiguous alias such as TEL or AI dynamically.
            safe = tuple(unicodedata.normalize("NFKC", str(n)) for n in names
                         if len(str(n)) >= 4 and str(n) not in {"ソフトバンク", "SoftBank", "SONY"})
            registry[str(code)] = tuple(registry.get(str(code), ())) + safe
    codes = []
    matched = []
    for code, names in registry.items():
        for name in names:
            if _match(title, name):
                matched.append((code, name))
    # A full listed-company alias wins over another issuer's contained alias.
    codes = sorted({code for code, name in matched
                    if not any(other != code and name.casefold() in longer.casefold()
                               and len(longer) > len(name) for other, longer in matched)})
    if len(codes) == 1 and any(_match(title, word) for word in MATERIAL_EVENTS):
        return "issuer_material_event", codes
    if len(codes) > 1 and any(_match(title, word) for word in MATERIAL_EVENTS):
        return "named_issuers_material_event", codes
    macro_rules = (
        (("日銀", "日本銀行", "Bank of Japan", "BOJ"),
         ("政策金利", "利上げ", "利下げ", "金融政策", "金融緩和", "金融引き締め", "国債買い入れ",
          "金利据え置き", "interest rate", "rate hike", "rate cut", "monetary policy")),
        (("日本", "国内", "Japan", "Japanese"),
         ("GDP", "消費者物価", "鉱工業生産", "貿易収支", "失業率", "実質賃金", "短観",
          "CPI", "industrial production", "trade balance", "unemployment rate")),
        (("日経平均", "TOPIX", "東証", "Nikkei 225", "Japan stocks", "Japanese stocks"),
         ("上昇", "下落", "反発", "続落", "続伸", "反落", "高値", "安値", "大引け",
          "前引け", "寄り付き", "rally", "fall", "rise", "decline", "close")),
        (("ドル円", "ドル/円", "円相場", "USD/JPY", "Japanese yen"),
         ("円高", "円安", "上昇", "下落", "介入", "急伸", "急落", "intervention", "rises", "falls")),
    )
    for subjects, facts in macro_rules:
        if any(_match(title, word) for word in subjects) and any(_match(title, word) for word in facts):
            return "japan_market_fact", []
    return "no_verified_japan_equity_link", []


def publication_time(entry, now=None, max_days=30):
    """Actual aware publisher time, never collection time; reject future data."""
    now = now or datetime.now(timezone.utc)
    for field in ("published", "updated"):
        raw = entry.get(field)
        result = None
        if isinstance(raw, str) and raw.strip():
            raw = re.sub(r"\sJST$", " +0900", raw.strip(), flags=re.IGNORECASE)
            try:
                result = parsedate_to_datetime(raw)
            except (ValueError, TypeError, OverflowError):
                try:
                    result = datetime.fromisoformat(raw.replace("Z", "+00:00"))
                except (ValueError, TypeError, OverflowError):
                    pass
        elif not raw:
            parsed = entry.get(field + "_parsed")
            if isinstance(parsed, (tuple, list)) and len(parsed) >= 6:
                try:
                    result = datetime(*parsed[:6], tzinfo=timezone.utc)
                except (ValueError, TypeError, OverflowError):
                    pass
        if result is None or result.tzinfo is None or result.utcoffset() is None:
            continue
        result = result.astimezone(timezone.utc)
        # A valid but future/stale published date must not be rescued by updated.
        if result > now or now - result > timedelta(days=max_days):
            return None
        return result
    return None


def normalize_score(value):
    """Old producer ranks 2/3/4 map to .5/.75/1; existing 0..1 stays intact."""
    try:
        score = float(value)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(score) or score < 0 or score > 4:
        return 0.0
    return score / 4 if score > 1 else score


# Safe literal used for sorting old rows without rewriting the database.
SCORE_SQL = "CASE WHEN score > 1 AND score <= 4 THEN score / 4.0 WHEN score >= 0 AND score <= 1 THEN score ELSE 0 END"


def canonical_url(value):
    try:
        p = urlsplit(str(value or ""))
        if p.scheme.lower() not in {"https", "http"} or not p.hostname or p.username or p.password:
            return ""
        port = p.port
        host = p.hostname.lower()
        if port and not (p.scheme.lower() == "https" and port == 443 or p.scheme.lower() == "http" and port == 80):
            host += ":" + str(port)
        query = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True)
                 if not k.lower().startswith("utm_") and k.lower() not in {"fbclid", "gclid"}]
        # Retain article IDs, revision and all unknown query parameters.
        return urlunsplit((p.scheme.lower(), host, p.path or "/", urlencode(sorted(query)), ""))
    except (ValueError, TypeError):
        return ""


def news_identity(url, title, published):
    """Collapse feed copies, while preserving different titles/revision dates."""
    url = canonical_url(url)
    if not url:
        return ""
    title = unicodedata.normalize("NFKC", clean_text(title))
    payload = "\n".join((url, title, str(published)))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


def news_uid(url, title, published):
    return "news_" + news_identity(url, title, published)
