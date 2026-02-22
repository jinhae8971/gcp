#!/usr/bin/env python3
"""
Weekly Savings & Deposit Product Blog Report Generator
Schedule: Every Saturday 5:00 AM KST (Friday 20:00 UTC)
Author: Winter AI Assistant

[데이터 수집 전략]
- 공식 사이트: 카카오뱅크 상품 페이지 실시간 스크래핑 (기준일 포함)
- 뉴스: 매일경제·아시아경제·데일리안·연합뉴스 RSS
- 링크: HEAD 요청으로 사전 검증, 깨진 링크 제거
"""

import os
import glob
import re
import time
import requests
import anthropic
import xml.etree.ElementTree as ET
from bs4 import BeautifulSoup
from datetime import datetime, timezone, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

KST = timezone(timedelta(hours=9))
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
}

VERIFY_URLS = [
    ("금융감독원 금융상품한눈에",  "https://finlife.fss.or.kr/Main.do"),
    ("저축은행중앙회 상품공시",     "https://www.fsb.or.kr"),
    ("은행연합회 금리공시",         "https://www.kfb.or.kr/info/interestRate.html"),
    ("카카오뱅크 상품 전체",        "https://www.kakaobank.com/products"),
    ("케이뱅크 예금",              "https://www.kbanknow.com/ib20/mnu/FPMFSA020010"),
    ("토스뱅크",                   "https://tossbank.com"),
]

DEPOSIT_KW  = ['예금','적금','금리','이자','특판','정기','저축','수신',
               '기준금리','금통위','예치','이율','수익률',
               'interest rate','deposit','savings','rate','yield','rate cut','rate hike','fed']
NEW_PROD_KW = ['신규','출시','특판','한정','이벤트','새롭게','론칭','개시',
               '오픈','판매시작','공개','선보','첫선','기념','new','launch','introduce']


# ──────────────────────────────────────────────
# 1. 공식 사이트 스크래핑 (카카오뱅크)
# ──────────────────────────────────────────────
def scrape_kakaobank() -> dict:
    """카카오뱅크 공식 상품 페이지에서 실제 금리·조건 수집"""
    result = {"source": "카카오뱅크 공식 홈페이지", "products": [], "scraped_at": ""}

    products_to_scrape = [
        {
            "name": "카카오뱅크 정기예금",
            "url":  "https://www.kakaobank.com/products/deposit",
            "type": "예금",
        },
        {
            "name": "카카오뱅크 자유적금",
            "url":  "https://www.kakaobank.com/products/freeSavings",
            "type": "적금",
        },
        {
            "name": "카카오뱅크 26주적금",
            "url":  "https://www.kakaobank.com/products/26weekSavings",
            "type": "적금",
        },
    ]

    now_kst = datetime.now(KST).strftime("%Y.%m.%d %H:%M")
    result["scraped_at"] = now_kst

    for prod in products_to_scrape:
        try:
            resp = requests.get(prod["url"], headers=HEADERS, timeout=12)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")

            info = {
                "name":        prod["name"],
                "type":        prod["type"],
                "url":         prod["url"],
                "rates":       [],
                "rate_table":  "",
                "conditions":  [],
                "scraped_at":  now_kst,
            }

            # ── 금리 테이블 (class="rate" 섹션)
            rate_divs = soup.find_all(class_=re.compile(r'\brate\b', re.I))
            for div in rate_divs:
                text = div.get_text(separator=" ", strip=True)
                if "%" in text and len(text) > 30:
                    info["rate_table"] = text[:600]
                    break

            # ── 텍스트에서 금리 패턴 추출
            full_text = soup.get_text(separator="\n")
            for line in full_text.split("\n"):
                line = line.strip()
                if re.search(r'연\s*[\d.]+\s*%', line) and len(line) < 120:
                    info["rates"].append(line)
            info["rates"] = list(dict.fromkeys(info["rates"]))[:10]

            # ── 가입 조건 (class="product") 섹션
            prod_divs = soup.find_all(class_=re.compile(r'\bproduct\b', re.I))
            for div in prod_divs:
                text = div.get_text(separator=" ", strip=True)
                if any(k in text for k in ["가입대상", "저축금액", "계약기간", "이자지급", "한도"]):
                    info["conditions"].append(text[:500])
                    if len(info["conditions"]) >= 2:
                        break

            result["products"].append(info)
            print(f"  ✓ {prod['name']}: 금리 {len(info['rates'])}개 수집")

        except Exception as e:
            print(f"  ✗ {prod['name']}: {e}")

    return result


# ──────────────────────────────────────────────
# 2. 링크 유효성 검증
# ──────────────────────────────────────────────
def verify_link(url: str) -> bool:
    if not url or not url.startswith("http"):
        return False
    try:
        r = requests.head(url, headers=HEADERS, timeout=5, allow_redirects=True)
        return r.status_code < 400
    except Exception:
        return False


def verify_links_parallel(news_list: list) -> list:
    with ThreadPoolExecutor(max_workers=12) as ex:
        futures = {ex.submit(verify_link, n["link"]): i
                   for i, n in enumerate(news_list) if n.get("link")}
        results = {}
        for f in as_completed(futures):
            results[futures[f]] = f.result()
    for i, n in enumerate(news_list):
        n["link_ok"] = results.get(i, False)
    ok = sum(1 for n in news_list if n["link_ok"])
    print(f"  → 링크 검증 완료: {ok}/{len(news_list)}건 유효")
    return news_list


# ──────────────────────────────────────────────
# 3. 뉴스 수집
# ──────────────────────────────────────────────
def get_finance_news() -> dict:
    feeds = [
        ("매일경제",     "https://www.mk.co.kr/rss/30100041/"),
        ("매일경제금융", "https://www.mk.co.kr/rss/50200011/"),
        ("아시아경제",   "https://www.asiae.co.kr/rss/all.htm"),
        ("데일리안",     "https://www.dailian.co.kr/rss/economy"),
        ("연합뉴스",     "https://www.yonhapnewstv.co.kr/browse/feed/"),
        ("Yahoo Finance","https://finance.yahoo.com/news/rssindex"),
        ("WSJ Markets",  "https://feeds.a.dj.com/rss/RSSMarketsMain.xml"),
        ("NBC Business", "https://feeds.nbcnews.com/nbcnews/public/business"),
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
                txt = (title + " " + desc).lower()
                is_deposit  = any(k.lower() in txt for k in DEPOSIT_KW)
                is_new_prod = any(k.lower() in txt for k in NEW_PROD_KW) and is_deposit
                all_news.append({
                    "source": source, "title": title, "link": link,
                    "desc": desc, "pub": pub,
                    "is_deposit": is_deposit, "is_new_prod": is_new_prod, "link_ok": False,
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

    all_news = verify_links_parallel(all_news)
    valid    = [n for n in all_news if n["link_ok"]]
    valid.sort(key=lambda x: (not x["is_new_prod"], not x["is_deposit"]))

    return {
        "new_products":    [n for n in valid if n["is_new_prod"]][:10],
        "general_finance": [n for n in valid if n["is_deposit"] and not n["is_new_prod"]][:12],
        "background":      [n for n in valid if not n["is_deposit"]][:6],
        "total_valid":     len(valid),
    }


# ──────────────────────────────────────────────
# 4. HTML 보고서 생성 (Claude AI)
# ──────────────────────────────────────────────
def generate_html(kakao: dict, news: dict, report_date: str, week_str: str) -> str:
    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))

    # ── 카카오뱅크 공식 데이터 포맷
    kakao_str = f"[수집 시각: {kakao['scraped_at']} / 출처: {kakao['source']}]\n"
    for p in kakao["products"]:
        kakao_str += f"\n◆ {p['name']} ({p['url']})\n"
        if p["rate_table"]:
            kakao_str += f"  금리 테이블: {p['rate_table'][:400]}\n"
        elif p["rates"]:
            kakao_str += f"  금리: {' | '.join(p['rates'][:6])}\n"
        if p["conditions"]:
            kakao_str += f"  가입조건: {p['conditions'][0][:300]}\n"

    # ── 뉴스 포맷
    def fmt_news(lst, label):
        if not lst:
            return f"  ({label}: 이번 주 수집된 기사 없음)"
        return "\n".join(
            f"  [{i+1}] [{n['source']}] {n['title']}\n"
            f"      URL: {n['link']}\n"
            f"      내용: {n['desc'][:200]}"
            for i, n in enumerate(lst[:10])
        )

    new_str     = fmt_news(news["new_products"],    "신규 상품 기사")
    general_str = fmt_news(news["general_finance"], "예적금 일반 기사")
    bg_str      = fmt_news(news["background"][:4],  "글로벌 금리 배경")
    verify_str  = "\n".join(f"  - {n}: {u}" for n, u in VERIFY_URLS)

    # 참고 기사 전체 (하단 출처용)
    all_refs = news["new_products"] + news["general_finance"]
    refs_str = "\n".join(
        f"  [{n['source']}] {n['title']} → {n['link']}"
        for n in all_refs
    )

    new_cnt  = len(news["new_products"])
    gen_cnt  = len(news["general_finance"])
    prod_cnt = len(kakao["products"])

    prompt = f"""당신은 친절하고 상냥한 은행원입니다. 오늘은 {report_date}입니다.

아래 ① 공식 사이트에서 직접 수집한 실제 데이터와 ② 이번 주 수집 기사를 모두 활용하여
이번 주({week_str}) 예금·적금 블로그 포스팅 HTML을 작성하세요.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
① 공식 사이트 실시간 데이터 ({prod_cnt}개 상품)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{kakao_str}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
② 이번 주 신규/특판 상품 기사 ({new_cnt}건)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{new_str}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
③ 예금·적금 일반 뉴스 ({gen_cnt}건)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{general_str}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
④ 글로벌 금리 환경 (배경)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{bg_str}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
⑤ 공식 검증 사이트
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{verify_str}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
⑥ 참고 기사 링크 전체 (하단 출처 섹션용)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{refs_str}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
팩트체크 절대 규칙
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. ①의 금리 수치 사용 시 → "(출처: 카카오뱅크 공식 홈페이지, {kakao['scraped_at']} 기준)" 표기
2. ②③의 기사 내용 사용 시 → 해당 기사 URL을 [출처] 버튼으로 표기
3. 위 데이터에 없는 구체적 금리 수치 작성 절대 금지
4. 다른 은행(신한·KB·우리 등) 언급 시 → 구체적 금리 대신 "공식 홈페이지 확인 필요" + 공식링크

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
HTML 구성 (이 순서 필수)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

① 최상단 데이터 현황 배너
   • 배경 #1a2744, 파란 테두리, 아이콘 📊
   • "공식 사이트 수집 {prod_cnt}개 상품 | 뉴스 기사 {news['total_valid']}건 | 링크 검증 완료"
   • 수집 시각 표시

② 제목 + 헤더 (비서 윈터 작성)

③ 서론 — 이번 주 금리·예적금 시장 동향
   (③④ 기사 + ④ 글로벌 배경 기반, 3~4문단)

④ ★ 이번 주 신규 상품 소식 ★ (별도 강조 섹션)
   스타일: border-top 3px solid #e3b341 (노란 강조선)
   • ②의 신규 기사가 있으면 → 각 기사를 카드로 표시 + [기사 원문 보기] 버튼
   • ②의 신규 기사가 없으면 → "이번 주 수집된 신규 상품 기사가 없습니다" + 공식 사이트 링크

⑤ 공식 데이터: 카카오뱅크 실시간 금리 (①번 데이터 사용)
   • 정기예금 금리 테이블 (기간별 금리를 HTML <table>로 시각화)
   • 자유적금·26주적금 금리 및 특징
   • 각 상품 우측 하단에 [공식 홈페이지 바로가기] 버튼 (실제 URL)
   • "(출처: 카카오뱅크 공식 홈페이지, YYYY.MM.DD 기준)" 명시

⑥ 시중은행·저축은행 동향 (③번 기사 기반)
   • 기사에 언급된 은행·상품 정리
   • 구체적 금리 대신 [공식 사이트 확인] 링크 제공

⑦ 유형별 추천
   직장인 / 사회초년생 / 시니어 — 각 1~2줄 + 추천 상품 링크

⑧ 하단 출처 섹션 (필수)
   • 참고한 기사 전체 목록 (클릭 가능 링크 버튼)
   • 공식 검증 사이트 전체 링크

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
디자인
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
- 다크 테마 (배경 #0d1117, 텍스트 #c9d1d9), 최대 폭 860px, 모바일 반응형
- [출처][원문보기][바로가기] 버튼: 배경 #21262d, 텍스트 #58a6ff, radius 6px, 새 탭
- 공식 데이터 금리: #3fb950 굵게 강조
- 신규 상품 섹션: border-top 3px solid #e3b341
- 공식 데이터 섹션: border-top 3px solid #58a6ff
- 비교표: 헤더 배경 #1f6feb, 홀짝 행 교대
- 섹션 카드: 배경 #161b22, 테두리 #30363d, radius 10px
- 공백 포함 2,200~2,600자 (정보량이 많으니 충분히 작성)

출력: <!DOCTYPE html> 로 시작하는 완전한 HTML만 (마크다운 코드블록 없이)"""

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=10000,
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

    def row(fp, prefix, icon):
        fn = os.path.basename(fp)
        d  = fn.replace(prefix, "").replace(".html", "")
        return f'    <tr><td><a href="{fn}">{icon} {d[:4]}년 {d[4:6]}월 {d[6:8]}일 보고서</a></td></tr>\n'

    html = f"""<!DOCTYPE html>
<html lang="ko"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>비서 윈터 리포트 센터</title>
<style>
  body{{font-family:'Noto Sans KR',Arial,sans-serif;background:#0d1117;color:#c9d1d9;margin:0;padding:20px}}
  h1{{color:#58a6ff;border-bottom:1px solid #30363d;padding-bottom:12px}}
  h2{{color:#58a6ff;font-size:1.05rem;margin:28px 0 10px}}
  table{{width:100%;border-collapse:collapse;margin-top:10px}}
  td{{padding:12px 16px;border-bottom:1px solid #21262d}}
  td a{{color:#58a6ff;text-decoration:none;font-size:1.05rem}}
  td a:hover{{text-decoration:underline}}
  .sub{{color:#8b949e;font-size:.9rem;margin-top:8px}}
  .nav{{display:flex;gap:16px;margin:14px 0 0;flex-wrap:wrap}}
  .nav a{{color:#3fb950;font-size:.9rem;text-decoration:none}}
</style></head><body>
  <h1>🤖 비서 윈터 리포트 센터</h1>
  <p class="sub">매주 자동 생성 | GitHub Actions</p>
  <div class="nav"><a href="dashboard.html">🖥️ 자동화 대시보드</a></div>
  <h2>📊 한국 증시 월요일 전망 보고서</h2>
  <p class="sub">매주 일요일 오전 7시 자동 생성</p>
  <table>{"".join(row(f,"report_","📊") for f in market_reports)}</table>
  <h2>🏦 예금·적금 상품 비교 보고서</h2>
  <p class="sub">매주 토요일 오전 5시 | 공식 사이트 실시간 데이터 + 뉴스 기사 출처 포함</p>
  <table>{"".join(row(f,"finance_","🏦") for f in finance_reports)}</table>
</body></html>"""

    with open(f"{docs_dir}/index.html", "w", encoding="utf-8") as f:
        f.write(html)
    print("  → index.html 업데이트 완료")


# ──────────────────────────────────────────────
# 6. 텔레그램 전송
# ──────────────────────────────────────────────
def send_telegram(report_url: str, report_date: str, kakao: dict, news: dict):
    token   = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        return

    # 카카오뱅크 대표 금리 한 줄 요약
    kakao_summary = ""
    for p in kakao["products"]:
        if p["rates"]:
            kakao_summary += f"• {p['name']}: {p['rates'][0]}\n"

    msg = (
        f"🏦 *예금·적금 상품 비교 보고서*\n"
        f"📅 {report_date}\n\n"
        f"📊 *공식 사이트 실시간 금리*\n"
        f"{kakao_summary}"
        f"_(출처: 카카오뱅크 공식, {kakao['scraped_at']} 기준)_\n\n"
        f"📰 뉴스 기사 {news['total_valid']}건 | 신규 상품 {len(news['new_products'])}건\n\n"
        f"🔍 *직접 확인*\n"
        f"• [금융감독원 금융상품한눈에](https://finlife.fss.or.kr/Main.do)\n"
        f"• [카카오뱅크 전체 상품](https://www.kakaobank.com/products)\n\n"
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
    print(f"  공식 사이트 스크래핑 + 뉴스 기사 출처")
    print("=" * 55)

    print("\n[1/5] 공식 사이트 스크래핑 (카카오뱅크)...")
    kakao = scrape_kakaobank()
    print(f"  → {len(kakao['products'])}개 상품 수집 완료")

    print("\n[2/5] 뉴스 수집 및 링크 검증 중...")
    news = get_finance_news()
    print(f"  → 유효 기사 {news['total_valid']}건 (신규:{len(news['new_products'])} / 일반:{len(news['general_finance'])})")

    print("\n[3/5] Claude AI 분석 및 HTML 생성 중...")
    html_content = generate_html(kakao, news, report_date, week_str)
    print("  → HTML 생성 완료")

    docs_dir    = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs")
    os.makedirs(docs_dir, exist_ok=True)
    output_path = f"{docs_dir}/finance_{file_date}.html"
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html_content)
    print(f"  → {output_path} 저장 완료")

    print("\n[4/5] 인덱스 업데이트...")
    update_index()

    report_url = f"https://jinhae8971.github.io/gcp/finance_{file_date}.html"
    print(f"\n[5/5] 텔레그램 전송...")
    send_telegram(report_url, report_date, kakao, news)

    print(f"\n✅ 완료!")
    print(f"   공식 데이터: 카카오뱅크 {len(kakao['products'])}개 상품")
    print(f"   뉴스 기사: {news['total_valid']}건")
    print(f"   보고서: {report_url}")


if __name__ == "__main__":
    main()
