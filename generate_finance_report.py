#!/usr/bin/env python3
"""
Weekly Savings & Deposit Product Blog Report Generator
Schedule: Every Saturday 5:00 AM KST (Friday 20:00 UTC)
Author: Winter AI Assistant

[팩트체크 정책]
- 수집된 기사에 근거한 내용만 작성
- 기사 출처 URL을 각 항목에 반드시 명시
- 기사 근거 없는 금리 수치는 절대 작성 금지
"""

import os
import glob
import re
import time
import requests
import anthropic
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta

KST = timezone(timedelta(hours=9))

# 공식 검증 URL (항상 하단에 포함)
VERIFY_URLS = [
    ("금융감독원 금융상품한눈에",    "https://finlife.fss.or.kr/Main.do"),
    ("저축은행중앙회 상품공시",       "https://www.fsb.or.kr/user.tdf?a=user.product.ProductApp&c=1001"),
    ("은행연합회 금리공시",           "https://www.kfb.or.kr/info/interestRate.html"),
    ("금융소비자정보포털 파인",        "https://fine.fss.or.kr/main/fin/finProd/finProdList.do"),
    ("카카오뱅크 예금",              "https://www.kakaobank.com/products/deposit"),
    ("케이뱅크 예금",               "https://www.kbanknow.com/ib20/mnu/FPMFSA020010"),
    ("토스뱅크 저축",               "https://tossbank.com/products/savings"),
]


# ──────────────────────────────────────────────
# 1. 금융 뉴스 수집
# ──────────────────────────────────────────────
def get_finance_news() -> list:
    """예적금·금리 관련 뉴스 수집 (출처 URL 포함)"""
    feeds = [
        ("아시아경제",  "https://www.asiae.co.kr/rss/all.htm"),
        ("연합뉴스",    "https://www.yonhapnewstv.co.kr/browse/feed/"),
        ("Yahoo Finance", "https://finance.yahoo.com/news/rssindex"),
        ("WSJ Markets", "https://feeds.a.dj.com/rss/RSSMarketsMain.xml"),
        ("NASDAQ News", "https://www.nasdaq.com/feed/rssoutbound?category=Markets"),
        ("NBC Business","https://feeds.nbcnews.com/nbcnews/public/business"),
        ("Fortune",     "https://fortune.com/feed/fortune-feeds/?id=3230629"),
    ]

    # 예적금·금리 관련 키워드
    keywords = [
        '예금', '적금', '금리', '이자', '특판', '정기', '저축', '수신',
        '기준금리', '금통위', '예치', '이율', '금융상품',
        'interest rate', 'deposit', 'savings', 'rate', 'fed', 'central bank',
        'rate cut', 'rate hike', 'yield',
    ]

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
        )
    }

    all_news, seen = [], set()

    for source, url in feeds:
        try:
            resp = requests.get(url, headers=headers, timeout=10)
            resp.raise_for_status()
            root  = ET.fromstring(resp.content)
            items = root.findall(".//item")
            cnt   = 0
            for item in items:
                title = item.findtext("title", "").strip()
                link  = item.findtext("link",  "").strip()
                desc  = item.findtext("description", "").strip()
                pub   = item.findtext("pubDate", "").strip()

                # HTML 태그 제거
                desc = re.sub(r'<[^>]+>', '', desc)[:400]

                if not title or title in seen:
                    continue

                seen.add(title)
                relevant = any(k.lower() in (title + " " + desc).lower() for k in keywords)
                all_news.append({
                    "source":   source,
                    "title":    title,
                    "link":     link,
                    "desc":     desc,
                    "pub":      pub,
                    "relevant": relevant,
                })
                cnt += 1
                if cnt >= 10:
                    break

            rel = sum(1 for n in all_news[-cnt:] if n["relevant"])
            print(f"  ✓ {source}: {cnt}건 (관련: {rel}건)")
        except Exception as e:
            print(f"  ✗ {source}: {e}")
        time.sleep(0.3)

    # 관련 기사 앞으로 정렬
    all_news.sort(key=lambda x: not x["relevant"])
    return all_news


# ──────────────────────────────────────────────
# 2. HTML 보고서 생성 (Claude AI - 기사 근거 필수)
# ──────────────────────────────────────────────
def generate_html(news: list, report_date: str, week_str: str) -> str:
    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))

    relevant = [n for n in news if n["relevant"]]
    others   = [n for n in news if not n["relevant"]]

    # 관련 기사 상세 (출처 URL 포함)
    relevant_str = "\n".join(
        f"  [{i+1}] [{n['source']}] {n['title']}\n"
        f"      URL: {n['link']}\n"
        f"      내용: {n['desc'][:200]}"
        for i, n in enumerate(relevant[:15])
    ) if relevant else "  (이번 주 예적금·금리 관련 한국어 기사 수집 없음)"

    # 참고용 기타 기사
    others_str = "\n".join(
        f"  [{n['source']}] {n['title']} | {n['link']}"
        for n in others[:10]
    )

    # 공식 검증 링크
    verify_str = "\n".join(f"  - {name}: {url}" for name, url in VERIFY_URLS)

    prompt = f"""당신은 친절하고 상냥한 은행원입니다. 오늘은 {report_date}입니다.

아래 수집된 실제 기사들을 바탕으로, 이번 주({week_str}) 예금·적금 상품 블로그 포스팅 HTML을 작성하세요.

━━━ 이번 주 수집된 예적금·금리 관련 기사 (팩트체크 근거) ━━━
{relevant_str}

━━━ 기타 참고 기사 (금리 환경 이해용) ━━━
{others_str}

━━━ 공식 검증 사이트 (하단 필수 포함) ━━━
{verify_str}

━━━ 팩트체크 작성 규칙 (절대 준수) ━━━

규칙 1: 위 수집 기사에 언급된 상품·금리·뉴스만 작성
규칙 2: 각 주장/수치 뒤에 반드시 출처 표기
  - 기사 근거: [출처: 기사 제목, URL]
  - 공식 사이트 근거: [출처: 사이트명, URL]
규칙 3: 기사에 없는 구체적 금리 수치는 절대 작성 금지
  → 대신 "현재 금리는 공식 사이트에서 확인하세요" + 링크 제공
규칙 4: 관련 기사가 없는 항목은 "이번 주 수집된 기사 없음 — 아래 공식 사이트에서 직접 확인하세요"로 명시
규칙 5: 보고서 최상단에 데이터 출처 안내 배너 삽입

━━━ 구성 ━━━
① [최상단] 팩트체크 안내 배너
   - 배경색 #1a2744, 파란 테두리
   - "📰 이 보고서는 {report_date} 수집된 실제 기사를 근거로 작성되었습니다"
   - "각 항목의 [출처] 링크를 클릭하면 원문 기사를 확인할 수 있습니다"
② 헤더 (제목, 날짜, 비서 윈터 작성)
③ 서론: 이번 주 금리·예적금 동향 (수집 기사 기반)
④ 본론A: 이번 주 주목 예금 상품/뉴스 (기사 근거, 각 항목에 [출처] 링크 버튼)
⑤ 본론B: 적금 관련 뉴스/상품 + 비교 (기사 근거)
⑥ 비교 테이블 (기사에 언급된 내용만, 없으면 테이블 대신 "기사 미확인" 안내)
⑦ 유형별 간단 추천 (직장인/사회초년생/시니어)
⑧ [하단 필수] 출처 및 직접 확인 링크 섹션
   - 참고 기사 목록 (클릭 가능한 링크)
   - 공식 검증 사이트 링크 전체

━━━ 디자인 ━━━
- 다크 테마 (배경 #0d1117, 텍스트 #c9d1d9)
- 최대 폭 820px 중앙 정렬, 모바일 반응형
- [출처] 링크 버튼: 배경 #21262d, 텍스트 #58a6ff, 둥근 모서리, 새 탭 열기
- 금리 수치: #3fb950 강조 (기사 근거 있을 때만)
- 비교표: 헤더 배경 #1f6feb
- 섹션 카드: 배경 #161b22, 테두리 #30363d
- 헤더: "비서 윈터 작성" 표시
- 공백 포함 2,000~2,500자

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
# 3. 인덱스 업데이트
# ──────────────────────────────────────────────
def update_index():
    docs_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs")

    market_reports  = sorted(glob.glob(f"{docs_dir}/report_*.html"),  reverse=True)
    finance_reports = sorted(glob.glob(f"{docs_dir}/finance_*.html"), reverse=True)

    def row(filepath, prefix, icon):
        fn   = os.path.basename(filepath)
        date = fn.replace(prefix, "").replace(".html", "")
        y, m, d = date[:4], date[4:6], date[6:8]
        return f'    <tr><td><a href="{fn}">{icon} {y}년 {m}월 {d}일 보고서</a></td></tr>\n'

    market_rows  = "".join(row(f, "report_",  "📊") for f in market_reports)
    finance_rows = "".join(row(f, "finance_", "🏦") for f in finance_reports)

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
    .nav-links {{ display:flex; gap:16px; margin:14px 0 0; flex-wrap:wrap; }}
    .nav-links a {{ color: #3fb950; font-size: 0.9rem; text-decoration:none; }}
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
  <p class="sub">매주 토요일 오전 5시 자동 생성 | 기사 출처 포함</p>
  <table>{finance_rows}</table>
</body>
</html>"""

    with open(f"{docs_dir}/index.html", "w", encoding="utf-8") as f:
        f.write(html)
    print("  → index.html 업데이트 완료")


# ──────────────────────────────────────────────
# 4. 텔레그램 전송
# ──────────────────────────────────────────────
def send_telegram(report_url: str, report_date: str, relevant_cnt: int):
    token   = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        print("  [WARN] 텔레그램 환경변수 미설정")
        return

    msg = (
        f"🏦 *예금·적금 상품 비교 보고서*\n"
        f"📅 {report_date}\n"
        f"📰 기사 근거 {relevant_cnt}건 수집\n\n"
        f"각 항목에 원문 기사 출처 링크 포함\n\n"
        f"🔍 *직접 확인*\n"
        f"• [금융감독원 금융상품한눈에](https://finlife.fss.or.kr/Main.do)\n"
        f"• [은행연합회 금리공시](https://www.kfb.or.kr/info/interestRate.html)\n\n"
        f"👉 [보고서 보기]({report_url})"
    )
    resp = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={"chat_id": chat_id, "text": msg, "parse_mode": "Markdown",
              "disable_web_page_preview": False},
        timeout=15,
    )
    print(f"  Telegram 응답: {resp.status_code}")


# ──────────────────────────────────────────────
# 메인
# ──────────────────────────────────────────────
def main():
    now         = datetime.now(KST)
    report_date = now.strftime("%Y년 %m월 %d일")
    file_date   = now.strftime("%Y%m%d")
    mon         = now - timedelta(days=now.weekday())
    fri         = mon + timedelta(days=4)
    week_str    = f"{mon.strftime('%m/%d')}~{fri.strftime('%m/%d')}"

    print("=" * 55)
    print(f"  🏦 예적금 보고서 생성 시작: {report_date}")
    print("  📰 팩트체크: 기사 출처 기반")
    print("=" * 55)

    print("\n[1/4] 금융 뉴스 수집 중...")
    news = get_finance_news()
    relevant_cnt = sum(1 for n in news if n["relevant"])
    print(f"  → 총 {len(news)}건 수집 / 예적금 관련: {relevant_cnt}건")

    print("\n[2/4] Claude AI 분석 및 HTML 생성 중...")
    html_content = generate_html(news, report_date, week_str)
    print("  → HTML 생성 완료")

    docs_dir    = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs")
    os.makedirs(docs_dir, exist_ok=True)
    output_path = f"{docs_dir}/finance_{file_date}.html"
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html_content)
    print(f"  → {output_path} 저장 완료")

    print("\n[3/4] 인덱스 페이지 업데이트 중...")
    update_index()

    report_url = f"https://jinhae8971.github.io/gcp/finance_{file_date}.html"
    print(f"\n[4/4] 텔레그램 알림 전송 중...")
    send_telegram(report_url, report_date, relevant_cnt)

    print(f"\n✅ 완료! 보고서 URL: {report_url}")


if __name__ == "__main__":
    main()
