#!/usr/bin/env python3
"""
Weekly Savings & Deposit Product Blog Report Generator
Schedule: Every Saturday 5:00 AM KST (Friday 20:00 UTC)
Author: Winter AI Assistant

[팩트체크 정책]
- FSS_API_KEY 환경변수가 있으면 금융감독원 금융상품한눈에 API로 실제 데이터 수집
- 없으면 AI 생성 + 출처 URL 의무화 + 팩트체크 경고 배너
- 항상: 금감원 상품 비교 링크, 각 은행 공식 사이트 링크 포함
"""

import os
import json
import glob
import re
import requests
import anthropic
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta

KST = timezone(timedelta(hours=9))

# 주요 은행 공식 예금 상품 페이지 URL (항상 출처로 제공)
BANK_OFFICIAL_URLS = {
    "KB국민은행":   "https://obank.kbstar.com/quics?page=C017480",
    "신한은행":     "https://www.shinhan.com/hpe/index.jsp#050101000000",
    "우리은행":     "https://www.wooribank.com/wb/html/savings/deposit.do",
    "하나은행":     "https://www.kebhana.com/cont/mall/mall08/mall0801/index.jsp",
    "NH농협은행":   "https://www.nonghyup.com/personal/savings/depositProduct.do",
    "IBK기업은행":  "https://www.ibk.co.kr/ibk.ibk?cmd=PBSNV0001M",
    "카카오뱅크":   "https://www.kakaobank.com/products/deposit",
    "케이뱅크":     "https://www.kbanknow.com/ib20/mnu/FPMFSA020010",
    "토스뱅크":     "https://tossbank.com/products/savings",
    "SC제일은행":   "https://www.standardchartered.co.kr/np/kr/pc/pb/sp/deposits/depositMain.jsp",
    "씨티은행":     "https://www.citibank.co.kr/ib20/mnu/KRRBPR010",
    "저축은행중앙회": "https://www.fsb.or.kr/user.tdf?a=user.product.ProductApp&c=1001&mc=menu_02_01_01",
}

VERIFY_URLS = {
    "금융감독원 금융상품한눈에": "https://finlife.fss.or.kr/Main.do",
    "저축은행중앙회 상품공시": "https://www.fsb.or.kr/user.tdf?a=user.product.ProductApp&c=1001&mc=menu_02_01_01",
    "은행연합회 금리공시": "https://www.kfb.or.kr/info/interestRate.html",
    "금융소비자정보포털 파인": "https://fine.fss.or.kr/main/fin/finProd/finProdList.do",
}


# ──────────────────────────────────────────────
# 1. 금융감독원 Open API (실제 데이터)
# ──────────────────────────────────────────────
def fetch_fss_products(api_key: str) -> dict:
    """금융감독원 금융상품한눈에 API로 실제 예적금 상품 조회"""
    base = "https://finlife.fss.or.kr/finlifeapi"
    results = {"deposits": [], "savings": [], "source": "FSS_API"}

    # 예금 상품 (은행 020000 / 저축은행 030300)
    for grp_no, grp_name in [("020000", "은행"), ("030300", "저축은행")]:
        for endpoint, ptype in [("depositProductsSearch", "예금"), ("savingProductsSearch", "적금")]:
            url = f"{base}/{endpoint}.json"
            try:
                resp = requests.get(url, params={
                    "auth": api_key,
                    "topFinGrpNo": grp_no,
                    "pageNo": "1"
                }, timeout=15)
                resp.raise_for_status()
                data = resp.json().get("result", {})
                if data.get("err_cd") != "000":
                    print(f"  [FSS] {grp_name} {ptype} 오류: {data.get('err_msg')}")
                    continue
                items = data.get("baseList", [])
                options = {o["fin_prdt_cd"]: o for o in data.get("optionList", [])}
                for item in items[:5]:
                    code = item.get("fin_prdt_cd", "")
                    opt  = options.get(code, {})
                    entry = {
                        "bank":       item.get("kor_co_nm", ""),
                        "product":    item.get("fin_prdt_nm", ""),
                        "join_way":   item.get("join_way", ""),
                        "join_member": item.get("join_member", ""),
                        "etc_note":   item.get("etc_note", ""),
                        "base_rate":  opt.get("intr_rate", "-"),
                        "max_rate":   opt.get("intr_rate2", "-"),
                        "save_trm":   opt.get("save_trm", "-"),
                        "intr_rate_type": opt.get("intr_rate_type_nm", ""),
                        "dcls_strt_day": item.get("dcls_strt_day", ""),
                        "type":       ptype,
                        "group":      grp_name,
                        "source_url": VERIFY_URLS["금융감독원 금융상품한눈에"],
                    }
                    if ptype == "예금":
                        results["deposits"].append(entry)
                    else:
                        results["savings"].append(entry)
                print(f"  ✓ FSS {grp_name} {ptype}: {len(items)}개 수집")
            except Exception as e:
                print(f"  ✗ FSS {grp_name} {ptype}: {e}")
    return results


# ──────────────────────────────────────────────
# 2. 금융 뉴스 수집
# ──────────────────────────────────────────────
def get_finance_news() -> list:
    """예적금·금리 관련 한국 금융 뉴스 수집"""
    feeds = [
        ("아시아경제", "https://www.asiae.co.kr/rss/all.htm"),
        ("연합뉴스 경제", "https://www.yonhapnewstv.co.kr/browse/feed/"),
        ("Yahoo Finance", "https://finance.yahoo.com/news/rssindex"),
        ("WSJ Markets",   "https://feeds.a.dj.com/rss/RSSMarketsMain.xml"),
        ("NASDAQ News",   "https://www.nasdaq.com/feed/rssoutbound?category=Markets"),
    ]
    deposit_keywords = ['예금', '적금', '금리', '이자', '특판', '정기', '저축', '수신',
                        '금통위', '기준금리', '예치', '이율', 'interest rate', 'deposit',
                        'savings', 'rate cut', 'rate hike']
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )
    }
    news, seen = [], set()
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
                desc  = item.findtext("description", "").strip()[:300]
                pub   = item.findtext("pubDate", "").strip()
                if title and title not in seen:
                    # 예적금 관련 키워드가 있는 기사 우선, 없어도 포함(AI 참고용)
                    is_relevant = any(k.lower() in (title + desc).lower() for k in deposit_keywords)
                    seen.add(title)
                    news.append({
                        "source":      source,
                        "title":       title,
                        "link":        link,
                        "desc":        desc,
                        "pub":         pub,
                        "relevant":    is_relevant,
                    })
                    cnt += 1
                    if cnt >= 10:
                        break
            print(f"  ✓ {source}: {cnt}건")
        except Exception as e:
            print(f"  ✗ {source}: {e}")

    # 관련 기사를 앞으로
    news.sort(key=lambda x: (not x["relevant"]))
    return news[:25]


# ──────────────────────────────────────────────
# 3. HTML 보고서 생성 (Claude AI)
# ──────────────────────────────────────────────
def generate_html(news: list, fss_data: dict,
                  report_date: str, week_str: str, has_fss: bool) -> str:
    """Claude API로 예적금 블로그 HTML 생성 (출처 필수 포함)"""
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    client  = anthropic.Anthropic(api_key=api_key)

    # 뉴스 문자열 (관련 기사만)
    relevant_news = [n for n in news if n["relevant"]]
    all_news      = news[:15]
    news_str = "\n".join(
        f"  [{n['source']}] {n['title']}"
        + (f" | 링크: {n['link']}" if n['link'] else "")
        for n in (relevant_news if relevant_news else all_news)
    )

    # FSS 실제 데이터 문자열
    fss_str = ""
    if has_fss and (fss_data.get("deposits") or fss_data.get("savings")):
        fss_str = "\n━━━ 금융감독원 금융상품한눈에 실제 데이터 (출처: finlife.fss.or.kr) ━━━\n"
        for item in fss_data.get("deposits", [])[:5]:
            fss_str += (
                f"  [{item['group']} 예금] {item['bank']} - {item['product']}\n"
                f"    기본금리: {item['base_rate']}% / 최고금리: {item['max_rate']}%"
                f" / 기간: {item['save_trm']}개월 / 가입방법: {item['join_way']}\n"
            )
        for item in fss_data.get("savings", [])[:5]:
            fss_str += (
                f"  [{item['group']} 적금] {item['bank']} - {item['product']}\n"
                f"    기본금리: {item['base_rate']}% / 최고금리: {item['max_rate']}%"
                f" / 기간: {item['save_trm']}개월 / 가입방법: {item['join_way']}\n"
            )

    # 공식 출처 URL 목록
    verify_str = "\n".join(f"  - {k}: {v}" for k, v in VERIFY_URLS.items())
    bank_str   = "\n".join(f"  - {k}: {v}" for k, v in list(BANK_OFFICIAL_URLS.items())[:8])

    data_source_note = (
        "※ 위 데이터는 금융감독원 금융상품한눈에 API에서 실시간 수집한 실제 데이터입니다."
        if has_fss else
        "※ FSS API 키 미설정으로 AI가 시장 동향 기반으로 생성한 콘텐츠입니다. "
        "반드시 아래 공식 출처에서 실제 금리를 확인하세요."
    )

    prompt = f"""당신은 친절하고 상냥한 은행원입니다. 오늘은 {report_date}입니다.

아래 데이터를 바탕으로 이번 주({week_str}) 한국 예금·적금 상품 블로그 포스팅 HTML을 작성하세요.

━━━ 이번 주 금융 뉴스 (수집된 실제 기사) ━━━
{news_str}

{fss_str}

━━━ 반드시 포함해야 할 공식 출처 URL ━━━
{verify_str}

━━━ 주요 은행 공식 상품 페이지 ━━━
{bank_str}

━━━ 데이터 신뢰도 안내 ━━━
{data_source_note}

━━━ 작성 요건 ━━━

[팩트체크 필수 규칙 - 반드시 준수]
1. 언급하는 모든 금융 상품은 반드시 다음 중 하나의 출처를 명시:
   - 위에 제공된 뉴스 기사 링크
   - 공식 은행 상품 페이지 URL
   - 금융감독원 금융상품한눈에 URL
2. AI가 금리를 임의로 생성할 경우, 해당 수치 옆에 "(AI 추정, 실제 금리는 공식 사이트 확인 필수)" 표시
3. FSS API 데이터가 있으면 해당 수치는 "(출처: 금감원 금융상품한눈에, {report_date} 기준)" 표시
4. 보고서 최상단에 팩트체크 경고 배너 반드시 삽입
5. 보고서 하단에 "출처 및 검증 링크" 섹션 반드시 삽입

[내용 구성]
① 팩트체크 경고 배너 (최상단 노란색/주황색 강조 박스)
② 제목 + 헤더 (비서 윈터 작성 표시)
③ 서론: 이번 주 금리 동향 (수집된 뉴스 기반)
④ 본론A: 신규/주목 예금 상품 3~4개 (각 상품에 출처 링크 포함)
⑤ 본론B: 적금 상품 2~3개 + 기존 인기 상품 비교표
⑥ 비교표 (HTML <table>, 금리 출처 URL 포함)
⑦ 유형별 추천 (직장인 / 자영업자 / 사회초년생 / 시니어)
⑧ 출처 및 검증 링크 섹션 (하단 필수)

[글쓰기 규칙]
- 독자 호칭: "고객님"
- 말투: 친절하고 상냥한 은행원
- 공백 포함 2,000~2,500자
- 금리 수치는 반드시 출처 표시

[디자인]
- 다크 테마 (배경 #0d1117, 텍스트 #c9d1d9)
- 최대 폭 820px 중앙 정렬, 모바일 반응형
- 팩트체크 배너: 주황색 배경 (#7d4e00), 흰 텍스트, 경고 아이콘 ⚠️
- 출처 링크: 초록색 (#3fb950), 새 탭으로 열기
- 금리 수치: #3fb950(초록) 강조
- 비교표: 헤더 배경 #1f6feb
- 카드형 섹션 박스 (배경 #161b22, 테두리 #30363d)
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
# 4. 인덱스 페이지 업데이트
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
  <p class="sub">매주 토요일 오전 5시 자동 생성 | 팩트체크 출처 포함</p>
  <table>{finance_rows}</table>
</body>
</html>"""

    with open(f"{docs_dir}/index.html", "w", encoding="utf-8") as f:
        f.write(html)
    print("  → index.html 업데이트 완료")


# ──────────────────────────────────────────────
# 5. 텔레그램 전송
# ──────────────────────────────────────────────
def send_telegram(report_url: str, report_date: str, has_fss: bool):
    token   = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        print("  [WARN] 텔레그램 환경변수 미설정")
        return

    data_badge = "✅ 금감원 실제 데이터" if has_fss else "⚠️ AI 추정 (출처 링크 포함)"
    msg = (
        f"🏦 *예금·적금 상품 비교 보고서*\n"
        f"📅 {report_date} | 데이터: {data_badge}\n\n"
        f"이번 주 예적금 상품 비교 + 출처 확인 링크 포함\n\n"
        f"🔍 *팩트체크 출처*\n"
        f"• [금융감독원 금융상품한눈에](https://finlife.fss.or.kr/Main.do)\n"
        f"• [저축은행중앙회 상품공시](https://www.fsb.or.kr)\n"
        f"• [은행연합회 금리공시](https://www.kfb.or.kr/info/interestRate.html)\n\n"
        f"👉 [보고서 보기]({report_url})"
    )
    resp = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={"chat_id": chat_id, "text": msg, "parse_mode": "Markdown",
              "disable_web_page_preview": False},
        timeout=15
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
    print("=" * 55)

    # FSS API 키 확인
    fss_api_key = os.environ.get("FSS_API_KEY", "")
    has_fss     = bool(fss_api_key)
    print(f"\n[팩트체크] FSS Open API: {'✅ 실제 데이터 사용' if has_fss else '⚠️ AI 추정 모드 (출처 링크 포함)'}")

    # FSS 실제 데이터 수집
    fss_data = {}
    if has_fss:
        print("\n[1/5] 금융감독원 금융상품한눈에 API 데이터 수집 중...")
        fss_data = fetch_fss_products(fss_api_key)
        print(f"  → 예금 {len(fss_data.get('deposits',[]))}개 / 적금 {len(fss_data.get('savings',[]))}개 수집")
    else:
        print("\n[1/5] FSS API 키 없음 → AI 추정 + 출처 링크 모드")

    print("\n[2/5] 금융 뉴스 수집 중...")
    news = get_finance_news()
    relevant = sum(1 for n in news if n.get("relevant"))
    print(f"  → {len(news)}개 수집 (예적금 관련: {relevant}개)")

    print("\n[3/5] Claude AI 분석 및 HTML 생성 중...")
    html_content = generate_html(news, fss_data, report_date, week_str, has_fss)
    print("  → HTML 생성 완료")

    docs_dir    = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs")
    os.makedirs(docs_dir, exist_ok=True)
    output_path = f"{docs_dir}/finance_{file_date}.html"
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html_content)
    print(f"  → {output_path} 저장 완료")

    print("\n[4/5] 인덱스 페이지 업데이트 중...")
    update_index()

    report_url = f"https://jinhae8971.github.io/gcp/finance_{file_date}.html"
    print(f"\n[5/5] 텔레그램 알림 전송 중...")
    send_telegram(report_url, report_date, has_fss)

    print(f"\n✅ 완료! 보고서 URL: {report_url}")
    print(f"   데이터 출처: {'금감원 FSS API (실제 데이터)' if has_fss else 'AI 추정 + 공식 사이트 링크'}")


if __name__ == "__main__":
    main()
