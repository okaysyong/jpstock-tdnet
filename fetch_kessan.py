"""
fetch_kessan.py (kabuyoho PC버전 v2)
"""
import os, sys, re, requests
from datetime import datetime, timedelta, timezone
import unicodedata
from bs4 import BeautifulSoup
from collector_parsing import STOCK_CODE_PATTERN

JST = timezone(timedelta(hours=9))
VPS_BASE_URL    = os.environ.get("VPS_BASE_URL", "https://jpstocklive.com")
VPS_PUSH_SECRET = os.environ.get("VPS_PUSH_SECRET", "")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "ja,en;q=0.9",
    "Referer": "https://kabuyoho.jp/",
}

def parse_kabuyoho_html(html: str, date_str: str) -> list:
    """Read the selected date's earnings table, never navigation or other stock lists."""
    datetime.strptime(date_str, '%Y-%m-%d')
    soup = BeautifulSoup(html, 'html.parser')
    container = soup.select_one('#stocklist') or soup.select_one('section.cldr_today')
    if container is None:
        raise RuntimeError('Earnings calendar page format changed')
    tables = [container] if container.name == 'table' else container.find_all('table')
    table = next((candidate for candidate in tables
                  if '銘柄' in ' '.join(th.get_text(' ', strip=True)
                                        for th in candidate.find_all('th'))
                  and '決算' in ' '.join(th.get_text(' ', strip=True)
                                        for th in candidate.find_all('th'))), None)
    if table is None:
        raise RuntimeError('Earnings calendar page format changed')
    items = []
    seen = set()
    for row in table.find_all('tr'):
        cells = row.find_all('td', recursive=False)
        if not cells:
            continue
        anchor = next((a for a in cells[0].find_all('a', href=True)
                       if re.search(r'[?&]bcode=(' + STOCK_CODE_PATTERN + ')', a['href'])), None)
        if anchor is None:
            continue
        if len(cells) < 4:
            raise RuntimeError('Earnings calendar row format changed')
        code = re.search(r'[?&]bcode=(' + STOCK_CODE_PATTERN + ')', anchor['href']).group(1)
        company = anchor.find('p')
        name = company.get_text(' ', strip=True) if company else str(anchor.get('title') or '').strip()
        announced = re.search(r'(?<![0-9])([0-9]{4})[/-]([0-9]{1,2})[/-]([0-9]{1,2})(?![0-9])',
                              cells[1].get_text(' ', strip=True))
        if not name or announced is None:
            raise RuntimeError('Earnings calendar row format changed')
        try:
            source_date = datetime(*map(int, announced.groups())).strftime('%Y-%m-%d')
        except ValueError:
            raise RuntimeError('Invalid earnings calendar source date') from None
        if source_date != date_str:
            continue
        # Only the scheduled period column counts. Later profit columns show prior quarters.
        period = unicodedata.normalize('NFKC', cells[3].get_text(' ', strip=True))
        period = '本決算' if period == '本' else period
        match = re.search(r'(1Q|2Q|3Q|4Q|本決算|中間|通期)', period)
        ktype = match.group(1) if match else ''
        key = f"{code}_{date_str}"
        if key in seen:
            continue
        seen.add(key)

        items.append({
            "code":          code,
            "name":          name[:20],
            "market":        "",
            "fiscal_period": ktype,
            "kessan_date":   date_str,
            "kessan_time":   "",
            "source":        "kabuyoho",
        })

    return items


def fetch_kabuyoho_date(date_str: str) -> list:
    datetime.strptime(date_str, '%Y-%m-%d')
    yyyymmdd = date_str.replace("-", "")
    yyyymm = date_str[:7].replace("-", "")
    url = f"https://kabuyoho.jp/calender?lst={yyyymmdd}&publ=off&ym={yyyymm}&sett=4"
    try:
        res = requests.get(url, headers=HEADERS, timeout=15)
        res.raise_for_status()
    except requests.RequestException:
        raise RuntimeError('Earnings calendar download failed') from None
    return parse_kabuyoho_html(res.text, date_str)

def push_to_vps(items):
    from collector_common import push_json
    return push_json(VPS_BASE_URL,"/push/kessan",{"items":items})

def main():
    now = datetime.now(JST)
    print(f"=== 결산예정 수집 ({now.strftime('%Y-%m-%d %H:%M JST')}) ===")

    all_items = []
    seen_keys = set()

    for delta in range(20):
        target = now + timedelta(days=delta)
        if target.weekday() >= 5:
            continue
        date_str = target.strftime("%Y-%m-%d")
        items = fetch_kabuyoho_date(date_str)
        new = 0
        for it in items:
            k = f"{it['code']}_{it['kessan_date']}"
            if k not in seen_keys:
                seen_keys.add(k)
                all_items.append(it)
                new += 1
        print(f"  {date_str}: {new}건")

    print(f"\n총 {len(all_items)}건")
    if not all_items:
        print("  ⚠️ 데이터 없음")
        sys.exit(0)

    for it in all_items[:5]:
        print(f"  {it['kessan_date']} [{it['code']}] {it['name']} {it['fiscal_period']}")
    if len(all_items) > 5:
        print(f"  ... 외 {len(all_items)-5}건")

    push_to_vps(all_items)
    print("=== 완료 ===")

if __name__ == "__main__":
    main()
