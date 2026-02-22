#!/usr/bin/env python3
"""
Weekly Savings & Deposit Product Blog Report Generator
Schedule: Every Saturday 5:00 AM KST (Friday 20:00 UTC)
Author: Winter AI Assistant
"""

import os
import json
import glob
import requests
import anthropic
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta

KST = timezone(timedelta(hours=9))


# ──────────────────────────────────────────────
# 1. 금융 뉴스 수집
# ──────────────────────────────────────────────
def get_finance_news() -> list:
    """금리·예적금 관련 뉴스 RSS 수집"""
    feeds = [
        ("한국경제 금융", "https://feeds.hankyung.com/news/finance.xml"),
        ("연합뉴스 경제", "https://www.yonhapnewstv.co.kr/browse/feed/"),
        ("Yahoo Finance", "https://finance.yahoo.com/news/rssindex"),
        ("WSJ Markets",   "https://feeds.a.dj.com/rss/RSSMarketsMain.xml"),
    ]
    news = []
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )
    }
    for source, url in feeds:
        try:
            resp = requests.get(url, headers=headers, timeout=10)
            resp.raise_for_status()
            root = ET.fromstring(resp.content)
            items = root.findall(".//item")[:5]
            for item in items:
                title = item.findtext("title", "").strip()
                link  = item.findtext("link", "").strip()
                desc  = item.findtext("description", "").strip()[:200]
                if title:
                    news.append({"source": source, "title": title, "link": link, "desc": desc})
        except Exception as e:
            print(f"  ✗ {source}: {e}")
    # 중복 제거
    seen, unique = set(), []
    for n in news:
        if n["title"] not in seen:
            seen.add(n["title"])
            unique.append(n)
    return unique[:20]


# ──────────────────────────────────────────────
# 2. HTML 보고서 생성 (Claude AI)
# ──────────────────────────────────────────────
def generate_html(news: list, report_date: str, week_str: str) -> str:
    """Claude API로 예적금 블로그 HTML 생성"""
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    client  = anthropic.Anthropic(api_key=api_key)

    news_str = "\n".join(
        [f"  [{n['source']}] {n['title']}" for n in news[:15]]
    ) if news else "  - 뉴스 수집 불가"

    prompt = f"""당신은 친절하고 상냥한 은행원입니다. 오늘은 {report_date}입니다.

아래 최신 금융 뉴스를 참고하여, 이번 주({week_str}) 한국 예금·적금 상품에 관한
블로그 포스팅 형식의 HTML 페이지를 작성하세요.

━━━ 최신 금융 뉴스 (참고용) ━━━
{news_str}

━━━ 작성 요건 ━━━

[내용 요건]
1. 이번 주 새롭게 출시되거나 금리가 변경된 예금·적금 상품 3~4개 소개
   (시중은행·인터넷은행·저축은행 골고루 포함)
2. 현재 시장에서 인기 있는 기존 주요 상품 2~3개와 상세 비교
3. 비교 항목:
   - 기본금리 / 우대금리 조건
   - 가입 조건 (대상, 한도)
   - 예치 기간 옵션
   - 중도 해지 시 불이익
   - 해당 상품만의 특장점과 단점
4. 비교표 (HTML <table> 형태로 시각화)
5. 사용자 유형별 추천: 직장인 / 자영업자 / 학생·사회초년생 / 시니어
6. 주의사항 및 가입 전 체크리스트
7. 공백 포함 2,000자~2,500자 분량
8. 상냥하고 친절한 은행원 말투 (독자를 "고객님"으로 호칭)

[구성]
① 제목: 이목을 끄는 한국어 제목
② 서론: 최근 금리 동향 및 이번 주 포인트
③ 본론A: 신규/변경 상품 소개 및 분석
④ 본론B: 기존 인기 상품 비교표 + 설명
⑤ 결론: 유형별 추천 + 가입 전 유의사항

[디자인 요건]
- 다크 테마 (배경 #0d1117, 텍스트 #c9d1d9)
- 블로그 스타일 (최대 폭 800px, 중앙 정렬)
- 금리 수치는 #3fb950(초록) 강조
- 비교표: 헤더 배경 #1f6feb, 행 교대 음영
- 카드형 섹션 박스
- 모바일 반응형
- 헤더에 "비서 윈터 작성" 표시

출력: <!DOCTYPE html> 로 시작하는 완전한 HTML만 출력 (마크다운 코드블록 없이)"""

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=8000,
        messages=[{"role": "user", "content": prompt}],
    )
    html = response.content[0].text
    if html.startswith("```"):
        html = html.split("\n", 1)[1]
        if html.endswith("```"):
            html = html.rsplit("```", 1)[0]
    return html.strip()


# ──────────────────────────────────────────────
# 3. 인덱스 페이지 업데이트
# ──────────────────────────────────────────────
def update_index():
    """docs/index.html 에 금융 보고서 목록 반영"""
    docs_dir = os.path.join(os.path.dirname(__file__), "docs")

    market_reports  = sorted(glob.glob(f"{docs_dir}/report_*.html"), reverse=True)
    finance_reports = sorted(glob.glob(f"{docs_dir}/finance_*.html"), reverse=True)

    def row(filepath, label_prefix):
        fn   = os.path.basename(filepath)
        date = fn.replace(label_prefix, "").replace(".html", "")
        y, m, d = date[:4], date[4:6], date[6:8]
        return f'    <tr><td><a href="{fn}">📄 {y}년 {m}월 {d}일 보고서</a></td></tr>\n'

    market_rows  = "".join(row(f, "report_")  for f in market_reports)
    finance_rows = "".join(row(f, "finance_") for f in finance_reports)

    html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>비서 윈터 리포트 센터</title>
  <style>
    body {{ font-family: 'Noto Sans KR', Arial, sans-serif; background: #0d1117; color: #c9d1d9; margin: 0; padding: 20px; }}
    h1   {{ color: #58a6ff; border-bottom: 1px solid #30363d; padding-bottom: 12px; }}
    h2   {{ color: #58a6ff; font-size: 1.05rem; margin: 28px 0 10px; }}
    table {{ width: 100%; border-collapse: collapse; margin-top: 10px; }}
    td   {{ padding: 12px 16px; border-bottom: 1px solid #21262d; }}
    td a {{ color: #58a6ff; text-decoration: none; font-size: 1.05rem; }}
    td a:hover {{ text-decoration: underline; }}
    .sub {{ color: #8b949e; font-size: 0.9rem; margin-top: 8px; }}
    .nav-links {{ display:flex; gap:16px; margin: 14px 0 0; flex-wrap:wrap; }}
    .nav-links a {{ color: #3fb950; font-size: 0.9rem; text-decoration:none; }}
    .nav-links a:hover {{ text-decoration:underline; }}
  </style>
</head>
<body>
  <h1>🤖 비서 윈터 리포트 센터</h1>
  <p class="sub">매주 자동 생성 | GitHub Actions</p>
  <div class="nav-links">
    <a href="dashboard.html">🖥️ 자동화 대시보드</a>
  </div>

  <h2>📊 한국 증시 월요일 전망 보고서</h2>
  <p class="sub">매주 일요일 오전 7시 자동 생성</p>
  <table>{market_rows}</table>

  <h2>🏦 예금·적금 상품 비교 보고서</h2>
  <p class="sub">매주 토요일 오전 5시 자동 생성</p>
  <table>{finance_rows}</table>
</body>
</html>"""

    with open(f"{docs_dir}/index.html", "w", encoding="utf-8") as f:
        f.write(html)
    print("  → index.html 업데이트 완료")


# ──────────────────────────────────────────────
# 4. 텔레그램 전송
# ──────────────────────────────────────────────
def send_telegram(report_url: str, report_date: str):
    """텔레그램으로 보고서 링크 전송"""
    token   = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        print("  [WARN] 텔레그램 환경변수 미설정")
        return

    msg = (
        f"🏦 *예금·적금 상품 비교 보고서*\n"
        f"📅 {report_date}\n\n"
        f"이번 주 새로 출시된 예적금 상품과\n"
        f"기존 인기 상품을 한눈에 비교해 드려요!\n\n"
        f"👉 [보고서 보기]({report_url})"
    )
    url  = f"https://api.telegram.org/bot{token}/sendMessage"
    resp = requests.post(url, json={
        "chat_id":    chat_id,
        "text":       msg,
        "parse_mode": "Markdown",
        "disable_web_page_preview": False,
    }, timeout=15)
    print(f"  Telegram 응답: {resp.status_code}")


# ──────────────────────────────────────────────
# 메인
# ──────────────────────────────────────────────
def main():
    now         = datetime.now(KST)
    report_date = now.strftime("%Y년 %m월 %d일")
    file_date   = now.strftime("%Y%m%d")
    # 이번 주 월~금 날짜 범위
    mon  = now - timedelta(days=now.weekday())
    fri  = mon + timedelta(days=4)
    week_str = f"{mon.strftime('%m/%d')}~{fri.strftime('%m/%d')}"

    print("=" * 55)
    print(f"  🏦 예적금 보고서 생성 시작: {report_date}")
    print("=" * 55)

    print("\n[1/4] 금융 뉴스 수집 중...")
    news = get_finance_news()
    print(f"  → {len(news)}개 뉴스 수집 완료")

    print("\n[2/4] Claude AI 분석 및 HTML 생성 중...")
    html_content = generate_html(news, report_date, week_str)
    print("  → HTML 생성 완료")

    docs_dir    = os.path.join(os.path.dirname(__file__), "docs")
    os.makedirs(docs_dir, exist_ok=True)
    output_path = f"{docs_dir}/finance_{file_date}.html"
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html_content)
    print(f"  → {output_path} 저장 완료")

    print("\n[3/4] 인덱스 페이지 업데이트 중...")
    update_index()

    report_url = f"https://jinhae8971.github.io/gcp/finance_{file_date}.html"
    print(f"\n[4/4] 텔레그램 알림 전송 중...")
    send_telegram(report_url, report_date)

    print(f"\n✅ 완료! 보고서 URL: {report_url}")


if __name__ == "__main__":
    main()
