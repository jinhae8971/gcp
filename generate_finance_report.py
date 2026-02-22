#!/usr/bin/env python3
"""
Weekly Savings & Deposit Product Blog Report Generator
Schedule: Every Saturday 5:00 AM KST (Friday 20:00 UTC)
Author: Winter AI Assistant

[팩트체크 정책]
- 수집된 기사에 근거한 내용만 작성
- HEAD 요청으로 모든 링크 유효성 사전 검증
- 신규 상품 코너 별도 구성
"""

import os
import glob
import re
import time
import requests
import anthropic
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

KST = timezone(timedelta(hours=9))

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

# 공식 검증 URL
VERIFY_URLS = [
    ("금융감독원 금융상품한눈에",  "https://finlife.fss.or.kr/Main.do"),
    ("저축은행중앙회 상품공시",     "https://www.fsb.or.kr/user.tdf?a=user.product.ProductApp&c=1001"),
    ("은행연합회 금리공시",         "https://www.kfb.or.kr/info/interestRate.html"),
    ("금융소비자정보포털 파인",      "https://fine.fss.or.kr/main/fin/finProd/finProdList.do"),
    ("카카오뱅크 예금",            "https://www.kakaobank.com/products/deposit"),
    ("케이뱅크 예금",              "https://www.kbanknow.com/ib20/mnu/FPMFSA020010"),
    ("토스뱅크 저축",              "https://tossbank.com/products/savings"),
]

# 예적금 관련 키워드
DEPOSIT_KW = [
    '예금', '적금', '금리', '이자', '특판', '정기', '저축', '수신',
    '기준금리', '금통위', '예치', '이율', '금융상품', '수익률',
    'interest rate', 'deposit', 'savings', 'rate', 'yield',
    'rate cut', 'rate hike', 'fed', 'central bank',
]

# 신규 상품 키워드
NEW_PRODUCT_KW = [
    '신규', '출시', '특판', '한정', '이벤트', '새롭게', '론칭', '개시',
    '오픈', '판매시작', '공개', '선보', '첫선', '기념',
    'new', 'launch', 'introduce', 'debut',
]


# ──────────────────────────────────────────────
# 1. 링크 유효성 검증
# ──────────────────────────────────────────────
def verify_link(url: str, timeout: int = 5) -> bool:
    """HEAD 요청으로 링크 유효성 확인 (200/301/302 → 유효)"""
    if not url or not url.startswith("http"):
        return False
    try:
        resp = requests.head(url, headers=HEADERS, timeout=timeout, allow_redirects=True)
        return resp.status_code < 400
    except Exception:
        return False


def verify_links_parallel(news_list: list) -> list:
    """병렬로 모든 기사 링크 유효성 검증"""
    print("  → 링크 유효성 검증 중...")
    results = {}

    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {
            executor.submit(verify_link, n["link"]): i
            for i, n in enumerate(news_list) if n.get("link")
        }
        for future in as_completed(futures):
            idx = futures[future]
            results[idx] = future.result()

    for i, news in enumerate(news_list):
        news["link_ok"] = results.get(i, False)

    ok_cnt = sum(1 for n in news_list if n.get("link_ok"))
    print(f"  → 링크 검증 완료: {ok_cnt}/{len(news_list)}건 유효")
    return news_list


# ──────────────────────────────────────────────
# 2. 뉴스 수집
# ──────────────────────────────────────────────
def get_finance_news() -> dict:
    """예적금·금리 관련 뉴스 수집 → 신규상품 / 일반 분류"""
    feeds = [
        # 검증된 한국 금융 뉴스
        ("매일경제",    "https://www.mk.co.kr/rss/30100041/"),
        ("매일경제금융","https://www.mk.co.kr/rss/50200011/"),
        ("아시아경제",  "https://www.asiae.co.kr/rss/all.htm"),
        ("데일리안",    "https://www.dailian.co.kr/rss/economy"),
        ("연합뉴스",    "https://www.yonhapnewstv.co.kr/browse/feed/"),
        # 글로벌 금융 환경
        ("Yahoo Finance","https://finance.yahoo.com/news/rssindex"),
        ("WSJ Markets", "https://feeds.a.dj.com/rss/RSSMarketsMain.xml"),
        ("NBC Business","https://feeds.nbcnews.com/nbcnews/public/business"),
    ]

    all_news, seen = [], set()

    for source, url in feeds:
        try:
            resp = requests.get(url, headers=HEADERS, timeout=10)
            resp.raise_for_status()
            root  = ET.fromstring(resp.content)
            items = root.findall(".//item")
            cnt   = 0
            for item in items:
                title = item.findtext("title", "").strip()
                link  = item.findtext("link",  "").strip()
                desc  = re.sub(r'<[^>]+>', '', item.findtext("description", "")).strip()[:400]
                pub   = item.findtext("pubDate", "").strip()

                if not title or title in seen:
                    continue
                seen.add(title)

                full_text = (title + " " + desc).lower()
                is_deposit  = any(k.lower() in full_text for k in DEPOSIT_KW)
                is_new_prod = any(k.lower() in full_text for k in NEW_PRODUCT_KW) and is_deposit

                all_news.append({
                    "source":      source,
                    "title":       title,
                    "link":        link,
                    "desc":        desc,
                    "pub":         pub,
                    "is_deposit":  is_deposit,
                    "is_new_prod": is_new_prod,
                    "link_ok":     False,  # 검증 전
                })
                cnt += 1
                if cnt >= 12:
                    break

            dep = sum(1 for n in all_news[-cnt:] if n["is_deposit"])
            new = sum(1 for n in all_news[-cnt:] if n["is_new_prod"])
            print(f"  ✓ {source}: {cnt}건 (예적금:{dep} / 신규:{new})")
        except Exception as e:
            print(f"  ✗ {source}: {e}")
        time.sleep(0.2)

    # 링크 유효성 검증 (병렬)
    all_news = verify_links_parallel(all_news)

    # 유효 링크만 남기고 분류
    valid_news = [n for n in all_news if n["link_ok"]]

    new_products = sorted(
        [n for n in valid_news if n["is_new_prod"]],
        key=lambda x: not x["is_deposit"]
    )
    general_finance = [n for n in valid_news if n["is_deposit"] and not n["is_new_prod"]]
    background      = [n for n in valid_news if not n["is_deposit"]]

    print(f"\n  [분류 결과] 신규상품:{len(new_products)}건 / 예적금일반:{len(general_finance)}건 / 배경:{len(background)}건")
    return {
        "new_products":    new_products[:10],
        "general_finance": general_finance[:10],
        "background":      background[:8],
        "total_valid":     len(valid_news),
    }


# ──────────────────────────────────────────────
# 3. 뉴스 섹션 포맷 (출처 URL 포함)
# ──────────────────────────────────────────────
def fmt_news_block(news_list: list, label: str) -> str:
    if not news_list:
        return f"  ({label} 수집된 기사 없음 — 공식 사이트에서 직접 확인 필요)"
    lines = []
    for i, n in enumerate(news_list, 1):
        link_status = "✓링크확인됨" if n.get("link_ok") else "✗링크불가"
        lines.append(
            f"  [{i}] [{n['source']}] {n['title']}\n"
            f"      URL({link_status}): {n['link']}\n"
            f"      내용: {n['desc'][:200]}"
        )
    return "\n".join(lines)


# ──────────────────────────────────────────────
# 4. HTML 보고서 생성 (Claude AI)
# ──────────────────────────────────────────────
def generate_html(news: dict, report_date: str, week_str: str) -> str:
    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))

    new_str     = fmt_news_block(news["new_products"],    "신규 상품")
    general_str = fmt_news_block(news["general_finance"], "예적금 일반")
    bg_str      = fmt_news_block(news["background"][:5],  "글로벌 금융 배경")
    verify_str  = "\n".join(f"  - {n}: {u}" for n, u in VERIFY_URLS)

    # 모든 유효 링크를 하단 참고 기사 목록용으로 수집
    all_valid = news["new_products"] + news["general_finance"]
    refs_str  = "\n".join(
        f"  [{n['source']}] {n['title']} → {n['link']}"
        for n in all_valid
    )

    prompt = f"""당신은 친절하고 상냥한 은행원입니다. 오늘은 {report_date}입니다.

아래 수집된 실제 기사들을 바탕으로, 이번 주({week_str}) 예금·적금 블로그 포스팅 HTML을 작성하세요.

━━━ [A] 이번 주 신규/특판 상품 관련 기사 ━━━
{new_str}

━━━ [B] 예금·적금·금리 일반 뉴스 ━━━
{general_str}

━━━ [C] 글로벌 금리 환경 (배경 참고용) ━━━
{bg_str}

━━━ 공식 검증 사이트 ━━━
{verify_str}

━━━ 참고 기사 링크 전체 (하단 출처 섹션용) ━━━
{refs_str}

━━━ 팩트체크 절대 규칙 ━━━
1. [A] 신규 상품 기사가 있으면 → "이번 주 신규 상품 소식" 섹션에 각 기사 출처 링크와 함께 상세히 소개
2. [A]가 없으면 → "이번 주 신규 상품 소식: 수집된 기사가 없습니다. 공식 사이트를 직접 확인하세요" + 링크 목록
3. 구체적 금리 수치 → 반드시 기사 URL 출처 표기. 기사 근거 없으면 숫자 대신 "공식 사이트 확인 필요" 표시
4. 모든 [출처] 버튼의 href는 위에 제공된 실제 URL만 사용 (링크 조작 절대 금지)
5. 최상단에 수집 기사 수와 링크 검증 현황을 명시한 배너 삽입

━━━ HTML 구성 (반드시 이 순서) ━━━

① 최상단 팩트체크 배너
   내용: "📰 {report_date} 수집 기사 {news['total_valid']}건 기반 | 링크 검증 완료"
   스타일: 배경 #1a2744, 파란 테두리 #388bfd, 패딩 충분히

② 제목 + 헤더 (비서 윈터 작성)

③ 서론 — 이번 주 금리·예적금 동향 (수집 기사 기반)

④ ★ 이번 주 신규 상품 소식 ★ (별도 강조 섹션, 노란 상단 테두리)
   - [A] 기사의 상품·뉴스를 각각 카드로 표시
   - 각 카드 우측에 [기사 원문 보기] 버튼 (배경 #21262d, 텍스트 #58a6ff)
   - [A] 없으면 "이번 주 수집된 신규 상품 기사 없음" + 공식 사이트 링크들

⑤ 예금·적금 시장 동향 및 주목 상품 ([B] 기사 기반)
   - 각 항목에 [출처] 버튼

⑥ 기존 상품 비교 테이블
   - 기사에 언급된 상품만 포함, 없으면 "기사 미확인 — 직접 확인 필요" + 공식링크

⑦ 유형별 간단 추천 (직장인 / 사회초년생 / 시니어)

⑧ 출처 및 직접 확인 링크 (하단 필수)
   - 참고한 기사 전체 목록 (클릭 가능한 링크 버튼)
   - 공식 검증 사이트 전체 (아이콘 포함)

━━━ 디자인 ━━━
- 다크 테마 (배경 #0d1117, 텍스트 #c9d1d9), 최대 폭 840px, 모바일 반응형
- 신규 상품 섹션: 상단 테두리 3px solid #e3b341 (노란색 강조)
- [출처]/[기사 원문] 버튼: 배경 #21262d, 텍스트 #58a6ff, border-radius 6px, 새 탭
- 금리 수치 (기사 근거 있을 때): #3fb950 굵게
- 비교표: 헤더 배경 #1f6feb, 홀짝 행 교대
- 섹션 카드: 배경 #161b22, 테두리 #30363d, border-radius 10px
- 공백 포함 2,000~2,500자

출력: <!DOCTYPE html> 로 시작하는 완전한 HTML만 출력 (마크다운 코드블록 없이)"""

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=9000,
        messages=[{"role": "user", "content": prompt}],
    )
    html = response.content[0].text
    if html.startswith("```"):
        html = html.split("\n", 1)[1]
        if html.endswith("```"):
            html = html.rsplit("```", 1)[0]
    return html.strip()


# ──────────────────────────────────────────────
# 5. 인덱스 업데이트
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
  <p class="sub">매주 토요일 오전 5시 자동 생성 | 기사 출처 링크 검증 포함</p>
  <table>{finance_rows}</table>
</body>
</html>"""

    with open(f"{docs_dir}/index.html", "w", encoding="utf-8") as f:
        f.write(html)
    print("  → index.html 업데이트 완료")


# ──────────────────────────────────────────────
# 6. 텔레그램 전송
# ──────────────────────────────────────────────
def send_telegram(report_url: str, report_date: str, news: dict):
    token   = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        print("  [WARN] 텔레그램 환경변수 미설정")
        return

    new_cnt = len(news["new_products"])
    msg = (
        f"🏦 *예금·적금 상품 비교 보고서*\n"
        f"📅 {report_date}\n"
        f"📰 수집 기사 {news['total_valid']}건 | 링크 검증 완료\n"
        f"✨ 신규 상품 소식: {new_cnt}건\n\n"
        f"🔍 *직접 확인*\n"
        f"• [금융감독원 금융상품한눈에](https://finlife.fss.or.kr/Main.do)\n"
        f"• [은행연합회 금리공시](https://www.kfb.or.kr/info/interestRate.html)\n\n"
        f"👉 [보고서 보기]({report_url})"
    )
    resp = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={"chat_id": chat_id, "text": msg,
              "parse_mode": "Markdown", "disable_web_page_preview": False},
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
    print(f"  🏦 예적금 보고서 생성: {report_date}")
    print(f"  📰 기사 출처 기반 | 링크 검증 포함")
    print("=" * 55)

    print("\n[1/4] 뉴스 수집 및 링크 검증 중...")
    news = get_finance_news()

    print("\n[2/4] Claude AI 분석 및 HTML 생성 중...")
    html_content = generate_html(news, report_date, week_str)
    print("  → HTML 생성 완료")

    docs_dir    = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs")
    os.makedirs(docs_dir, exist_ok=True)
    output_path = f"{docs_dir}/finance_{file_date}.html"
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html_content)
    print(f"  → {output_path} 저장 완료")

    print("\n[3/4] 인덱스 업데이트 중...")
    update_index()

    report_url = f"https://jinhae8971.github.io/gcp/finance_{file_date}.html"
    print(f"\n[4/4] 텔레그램 전송 중...")
    send_telegram(report_url, report_date, news)

    print(f"\n✅ 완료!")
    print(f"   신규 상품 기사: {len(news['new_products'])}건")
    print(f"   예적금 일반 기사: {len(news['general_finance'])}건")
    print(f"   보고서 URL: {report_url}")


if __name__ == "__main__":
    main()
