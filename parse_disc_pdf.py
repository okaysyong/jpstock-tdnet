# -*- coding: utf-8 -*-
"""
parse_disc_pdf.py — GitHub Actions에서 실행
TDnet 공시 PDF 핵심 수치 추출 → VPS 저장
대상: rank≥3 중 content가 비어있는 공시
"""
import os, re, requests, time
from datetime import datetime, timezone, timedelta

JST = timezone(timedelta(hours=9))
VPS_URL = os.environ.get("VPS_NEWS_API_URL", "https://jpstocklive.com")
VPS_TOKEN = os.environ.get("VPS_TOKEN", "")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
}

def extract_pdf_text(pdf_url: str) -> str:
    """PDF URL에서 텍스트 추출 (pypdf 사용)"""
    try:
        import io
        from pypdf import PdfReader
        r = requests.get(pdf_url, headers=HEADERS, timeout=20)
        if r.status_code != 200:
            return ""
        reader = PdfReader(io.BytesIO(r.content))
        text = ""
        for page in reader.pages[:3]:  # 최대 3페이지
            text += page.extract_text() or ""
            if len(text) > 3000:
                break
        return text[:3000]
    except Exception as e:
        print(f"  PDF 파싱 실패: {e}")
        return ""

def extract_key_figures(text: str, title: str) -> str:
    """핵심 수치 추출"""
    content = []

    # 상방/하방 수정 수치
    for pattern in [
        r'営業利益[^\d]*([▲△±\-\+]?\d[\d,\.]*)\s*(?:百万円|億円|千円)',
        r'経常利益[^\d]*([▲△±\-\+]?\d[\d,\.]*)\s*(?:百万円|億円|千円)',
        r'純利益[^\d]*([▲△±\-\+]?\d[\d,\.]*)\s*(?:百万円|億円|千円)',
        r'売上高[^\d]*([▲△±\-\+]?\d[\d,\.]*)\s*(?:百万円|億円|千円)',
        r'修正後.*?([▲△±\-\+]?\d[\d,\.]*)\s*(?:百万円|億円)',
        r'前回予想比.*?([▲△±\-\+\-]?\d+\.?\d*)\s*%',
    ]:
        m = re.search(pattern, text)
        if m:
            content.append(m.group(0)[:40].strip())
            if len(content) >= 3:
                break

    # TOB 가격
    if 'TOB' in title or '公開買付' in title:
        m = re.search(r'買付価格[^\d]*(\d[\d,\.]*)\s*円', text)
        if m:
            content.append(f"買付価格 {m.group(1)}円")

    # 株式分割 비율
    if '株式分割' in title:
        m = re.search(r'(\d+)\s*株[をに]\s*(\d+)\s*株', text)
        if m:
            content.append(f"{m.group(1)}→{m.group(2)}株分割")

    # 自社株買い 규모
    if '自己株式' in title and '取得' in title:
        m = re.search(r'取得総額[^\d]*(\d[\d,\.]*)\s*(?:百万円|億円)', text)
        if m:
            content.append(f"取得額 {m.group(0)[:20]}")

    return " / ".join(content) if content else ""

def get_empty_content_discs():
    """VPS에서 content가 비어있는 rank≥3 공시 가져오기"""
    try:
        r = requests.get(
            f"{VPS_URL}/tdnet?hours=48&min_rank=3",
            timeout=10
        )
        items = r.json().get("items", [])
        return [d for d in items if not d.get("content") and d.get("pdf_url")]
    except Exception as e:
        print(f"공시 목록 조회 실패: {e}")
        return []

def save_content(disclosure_id: str, content: str):
    """VPS에 content 저장"""
    try:
        r = requests.post(
            f"{VPS_URL}/push/disc_content",
            json={"disclosure_id": disclosure_id, "content": content, "token": VPS_TOKEN},
            timeout=10
        )
        return r.json().get("ok", False)
    except Exception as e:
        print(f"  저장 실패: {e}")
        return False

if __name__ == "__main__":
    print(f"[PDF파싱] 시작 {datetime.now(JST).strftime('%Y-%m-%d %H:%M JST')}")
    
    discs = get_empty_content_discs()
    print(f"[PDF파싱] content 비어있는 공시: {len(discs)}건")
    
    parsed = 0
    for d in discs[:15]:  # 최대 15건 (API 비용/시간 제한)
        name = d.get("name") or d.get("company_name", "")
        title = d.get("title", "")
        pdf_url = d.get("pdf_url", "")
        disc_id = d.get("disclosure_id", "")
        
        print(f"  처리: {name} - {title[:40]}")
        
        # PDF 텍스트 추출
        text = extract_pdf_text(pdf_url)
        if not text:
            print(f"    → 텍스트 없음")
            continue
        
        # 핵심 수치 추출
        figures = extract_key_figures(text, title)
        
        # content = 수치 + 본문 앞부분
        content = ""
        if figures:
            content += f"【핵심수치】{figures}\n"
            print(f"    → 수치: {figures}")
        content += text[:500]  # 본문 앞 500자
        
        if save_content(disc_id, content):
            parsed += 1
            print(f"    → 저장 완료")
        
        time.sleep(1)  # 레이트 리밋
    
    print(f"[PDF파싱] 완료: {parsed}건 저장")
