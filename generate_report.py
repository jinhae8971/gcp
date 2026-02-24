#!/usr/bin/env python3
"""
Weekly Monday Korean Stock Market Outlook Report Generator
Schedule: Every Sunday 7:00 AM KST (Saturday 22:00 UTC)
Author: Winter AI Assistant
"""

import os
import json
import glob
import time
import requests
import anthropic
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta

try:
    import yfinance as yf
    YFINANCE_OK = True
except ImportError:
    YFINANCE_OK = False

KST = timezone(timedelta(hours=9))
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}


# ──────────────────────────────────────────────
# 1. 미국/글로벌 시장 데이터 수집
# ──────────────────────────────────────────────
def fetch_ticker(sym: str, retries: int = 3) -> dict:
    """Yahoo Finance Chart API로 직접 조회 (Rate Limit 우회)"""
    # query1 / query2 교대 사용으로 rate limit 분산
    hosts = ["query1.finance.yahoo.com", "query2.finance.yahoo.com"]
    url_template = "https://{host}/v8/finance/chart/{sym}"
    params = {"range": "5d", "interval": "1d", "includePrePost": "false"}
    req_headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json",
        "Referer": "https://finance.yahoo.com/",
    }

    for attempt in range(retries):
        host = hosts[attempt % 2]
        url  = url_template.format(host=host, sym=sym)
        try:
            resp = requests.get(url, params=params, headers=req_headers, timeout=15)
            resp.raise_for_status()
            body   = resp.json()
            result = body["chart"]["result"][0]
            closes = result["indicators"]["quote"][0]["close"]
            closes = [c for c in closes if c is not None]
            if len(closes) < 2:
                return {}
            last = closes[-1]
            prev = closes[-2]
            chg  = last - prev
            pct  = (chg / prev) * 100
            ts   = result["timestamp"]
            date = datetime.fromtimestamp(ts[-1]).strftime("%Y-%m-%d")
            return {
                "price":  round(last, 2),
                "change": round(chg, 2),
                "pct":    round(pct, 2),
                "date":   date,
            }
        except Exception as e:
            wait = 2 * (attempt + 1)
            if attempt < retries - 1:
                time.sleep(wait)
            else:
                print(f"  [WARN] {sym}: {e}")
    return {}


def get_market_data() -> dict:
    """미국·글로벌 주요 시장 지표 수집"""
    symbols = {
        # ── 미국 주요 지수
        "S&P 500":          "^GSPC",
        "NASDAQ":           "^IXIC",
        "다우존스":         "^DJI",
        "Russell 2000":     "^RUT",
        # ── 선물 (야간/프리마켓 동향)
        "S&P 선물":         "ES=F",
        "나스닥 선물":      "NQ=F",
        # ── 반도체 (한국 시장 핵심 지표)
        "필라델피아 반도체": "^SOX",
        # ── 변동성
        "VIX 공포지수":     "^VIX",
        # ── 금리·달러
        "미국 10Y 국채금리": "^TNX",
        "달러인덱스 (DXY)": "DX-Y.NYB",
        # ── 환율
        "USD/KRW":          "KRW=X",
        "USD/JPY":          "JPY=X",
        "USD/CNY":          "CNY=X",
        # ── 한국 시장
        "코스피":           "^KS11",
        "코스닥":           "^KQ11",
        # ── 아시아 시장
        "닛케이 225":       "^N225",
        "항셍 지수":        "^HSI",
        "상하이 종합":      "000001.SS",
        # ── 원자재·암호화폐
        "금 (Gold)":        "GC=F",
        "은 (Silver)":      "SI=F",
        "구리 (Copper)":    "HG=F",
        "WTI 원유":         "CL=F",
        "BTC/USD":          "BTC-USD",
    }

    results = {}
    if not YFINANCE_OK:
        print("  [WARN] yfinance 미설치")
        return results

    for i, (name, sym) in enumerate(symbols.items()):
        data = fetch_ticker(sym)
        if data:
            results[name] = data
            direction = "▲" if data["pct"] >= 0 else "▼"
            print(f"  ✓ {name}: {data['price']} ({direction}{abs(data['pct'])}%)")
        else:
            print(f"  ✗ {name}: 수집 실패")
        # Rate limit 방지: 매 3건마다 0.5초 대기
        if (i + 1) % 3 == 0:
            time.sleep(0.5)

    return results


# ──────────────────────────────────────────────
# 2. 개별 주요 종목 데이터 수집
# ──────────────────────────────────────────────
def get_key_stocks() -> dict:
    """한국 증시 핵심 종목 미국 상장 ADR / 글로벌 테크 수집"""
    symbols = {
        # ── 미국 빅테크 (반도체·AI 동향)
        "엔비디아 (NVDA)":  "NVDA",
        "TSMC (TSM)":       "TSM",
        "AMD":              "AMD",
        "인텔 (INTC)":      "INTC",
        "마이크로소프트":   "MSFT",
        "애플 (AAPL)":      "AAPL",
        # ── 한국 ADR
        "삼성전자 ADR":     "SSNLF",
        "SK하이닉스 ADR":   "HXSCL",
    }
    results = {}
    for name, sym in symbols.items():
        data = fetch_ticker(sym)
        if data:
            results[name] = data
    return results


# ──────────────────────────────────────────────
# 3. 뉴스 수집 (신뢰도 높은 RSS)
# ──────────────────────────────────────────────
def get_news() -> list:
    """GitHub Actions 환경에서 안정적으로 작동하는 RSS 피드 수집"""
    feeds = [
        # Yahoo Finance (매우 안정적)
        ("Yahoo Finance - Markets",
         "https://finance.yahoo.com/news/rssindex"),
        ("Yahoo Finance - World",
         "https://finance.yahoo.com/rss/2.0/headline?s=^GSPC&region=US&lang=en-US"),
        # WSJ
        ("WSJ Markets",
         "https://feeds.a.dj.com/rss/RSSMarketsMain.xml"),
        # NASDAQ
        ("NASDAQ News",
         "https://www.nasdaq.com/feed/rssoutbound?category=Markets"),
        # Seeking Alpha
        ("Seeking Alpha",
         "https://seekingalpha.com/market_currents.xml"),
        # NBC Business
        ("NBC Business",
         "https://feeds.nbcnews.com/nbcnews/public/business"),
        # Barron's
        ("Barron's",
         "https://www.barrons.com/xml/rss/3_7523.xml"),
        # Fortune
        ("Fortune Finance",
         "https://fortune.com/feed/fortune-feeds/?id=3230629"),
    ]

    all_news = []
    for source, url in feeds:
        try:
            resp = requests.get(url, timeout=12, headers=HEADERS)
            resp.raise_for_status()
            root = ET.fromstring(resp.content)
            items = root.findall(".//item")[:5]
            for item in items:
                title   = item.find("title")
                desc    = item.find("description")
                pubdate = item.find("pubDate")
                if title is not None and title.text:
                    clean_title = title.text.strip()
                    # HTML 태그 제거
                    clean_title = ET.fromstring(
                        f"<t>{clean_title}</t>"
                    ).text or clean_title if "<" not in clean_title else clean_title
                    all_news.append({
                        "source": source,
                        "title":  clean_title,
                        "desc":   (desc.text or "")[:200].strip() if desc is not None else "",
                        "date":   pubdate.text if pubdate is not None else "",
                    })
            print(f"  ✓ {source}: {len(items)}건")
        except Exception as e:
            print(f"  ✗ {source}: {e}")

    # 중복 제거 (제목 기준)
    seen = set()
    unique = []
    for n in all_news:
        key = n["title"][:50]
        if key not in seen:
            seen.add(key)
            unique.append(n)

    return unique[:20]


# ──────────────────────────────────────────────
# 4. Claude AI로 HTML 보고서 생성
# ──────────────────────────────────────────────
def generate_html(market_data: dict, key_stocks: dict, news: list, report_date: str, today_name: str = "평일") -> str:
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    # ── 시장 지표 섹션별 분류
    def fmt_section(names):
        lines = []
        for name in names:
            d = market_data.get(name)
            if d and isinstance(d.get("pct"), float):
                arrow = "▲" if d["pct"] >= 0 else "▼"
                lines.append(f"  - {name}: {d['price']:,} ({arrow}{abs(d['pct']):.2f}%) [{d['date']}]")
        return "\n".join(lines) if lines else "  - 데이터 없음"

    us_indices = ["S&P 500", "NASDAQ", "다우존스", "Russell 2000"]
    us_futures  = ["S&P 선물", "나스닥 선물"]
    semi_vix    = ["필라델피아 반도체", "VIX 공포지수"]
    rates_fx    = ["미국 10Y 국채금리", "달러인덱스 (DXY)", "USD/KRW", "USD/JPY", "USD/CNY"]
    korea       = ["코스피", "코스닥"]
    asia        = ["닛케이 225", "항셍 지수", "상하이 종합"]
    commodities = ["금 (Gold)", "은 (Silver)", "구리 (Copper)", "WTI 원유", "BTC/USD"]

    # ── 주요 종목
    stock_lines = []
    for name, d in key_stocks.items():
        if isinstance(d.get("pct"), float):
            arrow = "▲" if d["pct"] >= 0 else "▼"
            stock_lines.append(f"  - {name}: ${d['price']} ({arrow}{abs(d['pct']):.2f}%)")
    stocks_str = "\n".join(stock_lines) if stock_lines else "  - 데이터 없음"

    # ── 뉴스
    news_str = "\n".join(
        [f"  [{n['source']}] {n['title']}" for n in news[:15]]
    ) if news else "  - 뉴스 수집 불가"

    prompt = f"""당신은 한국 증시 전문 애널리스트입니다. 오늘은 {report_date} ({today_name})입니다.
아래 데이터를 분석하여 오늘 장중·금일 한국 증시 전망 보고서를 작성하세요.

━━━ 한국 증시 직전 거래일 마감 (가장 중요) ━━━
{fmt_section(korea)}
※ 위 코스피·코스닥 종가를 기준으로 금일({today_name}) 예상 범위를 산출하세요.

━━━ 미국 주요 지수 (주간 마감) ━━━
{fmt_section(us_indices)}

━━━ 선물 (마감 후 동향) ━━━
{fmt_section(us_futures)}

━━━ 반도체 지수 / 변동성 ━━━
{fmt_section(semi_vix)}

━━━ 금리 / 환율 ━━━
{fmt_section(rates_fx)}

━━━ 아시아 시장 ━━━
{fmt_section(asia)}

━━━ 원자재 / 암호화폐 ━━━
{fmt_section(commodities)}

━━━ 글로벌 주요 종목 ━━━
{stocks_str}

━━━ 주말 주요 뉴스 (영문) ━━━
{news_str}

━━━ 작성 요건 ━━━
완성된 HTML 페이지를 작성하세요.

디자인 요건:
- 다크 테마 (배경 #0d1117, 텍스트 #c9d1d9)
- 전문 금융 리포트 스타일 / 모바일 반응형
- 상승 수치: #3fb950(초록) / 하락 수치: #f85149(빨강)
- 카드형 섹션 구성

필수 섹션:
1. 헤더 (제목, 날짜, "비서 윈터 작성" 표시)

2. ★ 한국 증시 전망 하이라이트 (헤더 바로 아래, 가장 눈에 띄게 배치)
   - 금일({today_name}) 코스피 예상 범위: 반드시 위 "한국 증시 직전 거래일 마감" 데이터의 실제 종가를 기준으로 산출 (고정 예시 숫자 절대 금지, 대형 숫자로 표시)
   - 전반적 전망 신호: 🟢강세 / 🟡중립 / 🔴약세 중 하나를 크게 표시
   - 핵심 포인트 3줄 (불릿) — 가장 중요한 시장 동인 요약
   - 주목 업종 TOP 3 (칩/태그 형태로 표시)
   이 섹션은 보고서를 열자마자 한눈에 파악할 수 있도록 시각적으로 강조할 것

3. 미국 증시 최근 마감 요약 (지수별 컬러 테이블)
4. 글로벌 시장 현황 (환율, 금리, 원자재[금·은·구리·WTI], 아시아)
5. 반도체 섹터 심층 분석 (필라델피아 반도체 + NVDA/TSMC 동향)
6. 주요 이슈 Top 5 (뉴스 기반 한국어 요약)
7. 금일({today_name}) 코스피/코스닥 시나리오 (A강세/B중립/C약세, 예상 지수 범위 포함)
8. 업종별 전망 (반도체, 자동차, 금융, 조선·방산, 바이오)
9. 핵심 투자 포인트 3가지
10. 금주 주요 일정 (날짜·이벤트·영향도 표)
11. 면책 고지 푸터

출력: <!DOCTYPE html> 로 시작하는 완전한 HTML만 출력 (마크다운 코드블록 없이)"""

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=8000,
        messages=[{"role": "user", "content": prompt}],
    )

    html = response.content[0].text
    # 혹시 마크다운 코드블록이 포함된 경우 제거
    if html.startswith("```"):
        html = html.split("\n", 1)[1]
        if html.endswith("```"):
            html = html.rsplit("```", 1)[0]
    return html.strip()


# ──────────────────────────────────────────────
# 5. 인덱스 페이지 업데이트
# ──────────────────────────────────────────────
def update_index():
    reports = sorted(
        [os.path.basename(f) for f in glob.glob("docs/report_*.html")],
        reverse=True,
    )
    rows = ""
    for r in reports:
        date_str = r.replace("report_", "").replace(".html", "")
        try:
            d = datetime.strptime(date_str, "%Y%m%d")
            label = d.strftime("%Y년 %m월 %d일")
        except Exception:
            label = date_str
        rows += f'<tr><td><a href="{r}">📄 {label} 한국 증시 전망 보고서</a></td></tr>\n'

    html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>한국 증시 월요일 전망 보고서</title>
  <style>
    body {{ font-family: 'Noto Sans KR', Arial, sans-serif; background: #0d1117; color: #c9d1d9; margin: 0; padding: 20px; }}
    h1 {{ color: #58a6ff; border-bottom: 1px solid #30363d; padding-bottom: 12px; }}
    table {{ width: 100%; border-collapse: collapse; margin-top: 20px; }}
    td {{ padding: 12px 16px; border-bottom: 1px solid #21262d; }}
    td a {{ color: #58a6ff; text-decoration: none; font-size: 1.05rem; }}
    td a:hover {{ text-decoration: underline; }}
    .sub {{ color: #8b949e; font-size: 0.9rem; margin-top: 8px; }}
  </style>
</head>
<body>
  <h1>📊 한국 증시 월요일 전망 보고서</h1>
  <p class="sub">평일 매일 오전 8시 자동 생성 | 비서 윈터</p>
  <table>
    {rows if rows else '<tr><td>아직 생성된 보고서가 없습니다.</td></tr>'}
  </table>
</body>
</html>"""

    with open("docs/index.html", "w", encoding="utf-8") as f:
        f.write(html)


# ──────────────────────────────────────────────
# 6. 텔레그램 전송
# ──────────────────────────────────────────────
def send_telegram(pages_url: str, market_data: dict, news: list):
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id   = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not bot_token or not chat_id:
        print("  [WARN] Telegram 환경변수 미설정")
        return

    def fmt(key):
        d = market_data.get(key, {})
        if not d or not isinstance(d.get("pct"), float):
            return "N/A"
        arrow = "▲" if d["pct"] >= 0 else "▼"
        return f"{d['price']:,} ({arrow}{abs(d['pct']):.2f}%)"

    # 주요 뉴스 헤드라인 3개
    headlines = "\n".join(
        [f"  • {n['title'][:60]}..." for n in news[:3]]
    ) if news else "  • 뉴스 없음"

    sp_e   = "📈" if market_data.get("S&P 500",  {}).get("pct", 0) >= 0 else "📉"
    nq_e   = "📈" if market_data.get("NASDAQ",   {}).get("pct", 0) >= 0 else "📉"
    sox_e  = "📈" if market_data.get("필라델피아 반도체", {}).get("pct", 0) >= 0 else "📉"
    vix    = market_data.get("VIX 공포지수", {}).get("price", "N/A")
    usdkrw = market_data.get("USD/KRW", {}).get("price", "N/A")

    text = (
        "🗞 <b>월요일 한국 증시 전망 보고서 발행</b>\n\n"
        f"<b>📊 미국 증시 주간 마감</b>\n"
        f"{sp_e} S&P 500      : {fmt('S&P 500')}\n"
        f"{nq_e} NASDAQ       : {fmt('NASDAQ')}\n"
        f"{sox_e} 필라델피아반도체: {fmt('필라델피아 반도체')}\n\n"
        f"<b>💱 환율 / 변동성</b>\n"
        f"  USD/KRW : {usdkrw}\n"
        f"  VIX     : {vix}\n\n"
        f"<b>📰 주요 뉴스</b>\n{headlines}\n\n"
        f"🔗 <a href=\"{pages_url}\">전체 보고서 보기</a>"
    )

    resp = requests.post(
        f"https://api.telegram.org/bot{bot_token}/sendMessage",
        json={"chat_id": chat_id, "text": text, "parse_mode": "HTML",
              "disable_web_page_preview": False},
        timeout=10,
    )
    print(f"  Telegram 응답: {resp.status_code}")


# ──────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────
def main():
    now         = datetime.now(KST)
    report_date = now.strftime("%Y년 %m월 %d일")
    filename    = f"report_{now.strftime('%Y%m%d')}.html"
    day_names   = ["월요일", "화요일", "수요일", "목요일", "금요일", "토요일", "일요일"]
    today_name  = day_names[now.weekday()]  # 0=월, 6=일

    print("=" * 55)
    print(f"  📊 보고서 생성 시작: {report_date}")
    print("=" * 55)

    print("\n[1/5] 미국·글로벌 시장 데이터 수집 중...")
    market_data = get_market_data()
    print(f"  → {len(market_data)}개 지표 수집 완료")

    print("\n[2/5] 주요 종목 데이터 수집 중...")
    key_stocks = get_key_stocks()
    print(f"  → {len(key_stocks)}개 종목 수집 완료")

    print("\n[3/5] 뉴스 수집 중...")
    news = get_news()
    print(f"  → {len(news)}개 뉴스 수집 완료")

    print("\n[4/5] Claude AI 분석 및 HTML 생성 중...")
    html_content = generate_html(market_data, key_stocks, news, report_date, today_name)
    os.makedirs("docs", exist_ok=True)
    with open(f"docs/{filename}", "w", encoding="utf-8") as f:
        f.write(html_content)
    update_index()
    print(f"  → docs/{filename} 저장 완료")

    print("\n[5/5] 텔레그램 알림 전송 중...")
    pages_url = f"https://jinhae8971.github.io/gcp/{filename}"
    send_telegram(pages_url, market_data, news)

    print(f"\n✅ 완료! 보고서 URL: {pages_url}")


if __name__ == "__main__":
    main()
