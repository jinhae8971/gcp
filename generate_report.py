#!/usr/bin/env python3
"""
Weekly Monday Korean Stock Market Outlook Report Generator
Schedule: Every Sunday 7:00 AM KST (Saturday 22:00 UTC)
Author: Winter AI Assistant
"""

import os
import json
import glob
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


# ──────────────────────────────────────────────
# 1. 시장 데이터 수집
# ──────────────────────────────────────────────
def get_market_data():
    symbols = {
        "S&P 500":      "^GSPC",
        "NASDAQ":       "^IXIC",
        "다우존스":     "^DJI",
        "USD/KRW":      "KRW=X",
        "BTC/USD":      "BTC-USD",
        "금 (Gold)":    "GC=F",
        "WTI 원유":     "CL=F",
        "VIX 공포지수": "^VIX",
    }
    results = {}
    if not YFINANCE_OK:
        return results

    for name, sym in symbols.items():
        try:
            ticker = yf.Ticker(sym)
            hist = ticker.history(period="5d")
            if hist.empty or len(hist) < 2:
                continue
            last = float(hist["Close"].iloc[-1])
            prev = float(hist["Close"].iloc[-2])
            chg  = last - prev
            pct  = (chg / prev) * 100
            results[name] = {
                "price":  round(last, 2),
                "change": round(chg, 2),
                "pct":    round(pct, 2),
                "date":   hist.index[-1].strftime("%Y-%m-%d"),
            }
        except Exception as e:
            print(f"  [WARN] {name} ({sym}): {e}")

    return results


# ──────────────────────────────────────────────
# 2. 뉴스 수집 (RSS)
# ──────────────────────────────────────────────
def get_news():
    feeds = [
        ("Reuters Business",   "https://feeds.reuters.com/reuters/businessNews"),
        ("CNBC Markets",       "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=20910258"),
        ("MarketWatch",        "https://feeds.marketwatch.com/marketwatch/topstories/"),
        ("Investing.com KR",   "https://kr.investing.com/rss/news_301.rss"),
        ("Bloomberg Markets",  "https://feeds.bloomberg.com/markets/news.rss"),
    ]
    headers = {"User-Agent": "Mozilla/5.0 (compatible; MarketBot/1.0)"}
    all_news = []

    for source, url in feeds:
        try:
            resp = requests.get(url, timeout=10, headers=headers)
            root = ET.fromstring(resp.content)
            for item in root.findall(".//item")[:5]:
                title   = item.find("title")
                desc    = item.find("description")
                pubdate = item.find("pubDate")
                if title is not None and title.text:
                    all_news.append({
                        "source":  source,
                        "title":   title.text.strip(),
                        "desc":    (desc.text or "")[:200].strip() if desc is not None else "",
                        "date":    pubdate.text if pubdate is not None else "",
                    })
        except Exception as e:
            print(f"  [WARN] RSS {source}: {e}")

    return all_news[:20]


# ──────────────────────────────────────────────
# 3. Claude AI로 HTML 보고서 생성
# ──────────────────────────────────────────────
def generate_html(market_data: dict, news: list, report_date: str) -> str:
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    # 시장 데이터 텍스트 변환
    market_lines = []
    for name, d in market_data.items():
        if isinstance(d.get("pct"), float):
            arrow = "▲" if d["pct"] >= 0 else "▼"
            color = "상승" if d["pct"] >= 0 else "하락"
            market_lines.append(
                f"- {name}: {d['price']} ({arrow}{abs(d['pct'])}% {color}) [{d['date']}]"
            )
    market_str = "\n".join(market_lines) if market_lines else "데이터 수집 불가"

    # 뉴스 텍스트 변환
    news_str = "\n".join(
        [f"[{n['source']}] {n['title']}" for n in news[:15]]
    ) if news else "뉴스 수집 불가"

    prompt = f"""당신은 한국 증시 전문 애널리스트입니다. 오늘은 {report_date} (일요일)입니다.

아래 데이터를 바탕으로 내일(월요일) 한국 증시 전망 보고서를 작성해주세요.

## 미국 증시 주간 마감 데이터
{market_str}

## 주말 주요 글로벌 뉴스
{news_str}

---

완성된 HTML 페이지를 작성해주세요. 조건:

1. **디자인**: 다크 테마, 전문적이고 세련된 금융 리포트 스타일
2. **반응형**: 모바일/PC 모두 최적화
3. **포함 섹션**:
   - 헤더 (보고서 제목, 날짜, "비서 윈터 작성")
   - 미국 증시 마감 요약 (컬러 테이블 — 상승: 초록, 하락: 빨강)
   - 주요 주말 이슈 Top 5 분석
   - 월요일 코스피/코스닥 시나리오 전망 (A: 강세 / B: 중립 / C: 약세, 각 확률 포함)
   - 업종별 전망 (반도체, 자동차, 금융, 조선·방산, 바이오)
   - 핵심 투자 포인트 (불릿 포인트)
   - 이번 주 주요 일정 (날짜별 표)
   - 푸터 (면책 고지, 자동 생성 안내)
4. **언어**: 한국어 전체
5. **출력**: ```html 없이 <!DOCTYPE html> 로 바로 시작하는 완전한 HTML 코드만 출력

반드시 완성된 단일 HTML 파일만 출력하세요."""

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=8000,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text


# ──────────────────────────────────────────────
# 4. 인덱스 페이지 업데이트
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
  <p class="sub">매주 일요일 오전 7시 자동 생성 | 비서 윈터</p>
  <table>
    {rows if rows else '<tr><td>아직 생성된 보고서가 없습니다.</td></tr>'}
  </table>
</body>
</html>"""

    with open("docs/index.html", "w", encoding="utf-8") as f:
        f.write(html)


# ──────────────────────────────────────────────
# 5. 텔레그램 전송
# ──────────────────────────────────────────────
def send_telegram(pages_url: str, market_data: dict):
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id   = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not bot_token or not chat_id:
        print("  [WARN] Telegram 환경변수 미설정, 전송 건너뜀")
        return

    sp  = market_data.get("S&P 500", {})
    nq  = market_data.get("NASDAQ", {})
    dji = market_data.get("다우존스", {})

    def fmt(d):
        if not d or not isinstance(d.get("pct"), float):
            return "N/A"
        arrow = "▲" if d["pct"] >= 0 else "▼"
        return f"{d['price']:,.2f} ({arrow}{abs(d['pct']):.2f}%)"

    sp_e  = "📈" if sp.get("pct", 0) >= 0 else "📉"
    nq_e  = "📈" if nq.get("pct", 0) >= 0 else "📉"
    dji_e = "📈" if dji.get("pct", 0) >= 0 else "📉"

    text = (
        "🗞 <b>월요일 한국 증시 전망 보고서 발행</b>\n\n"
        f"{sp_e} S&P 500  : {fmt(sp)}\n"
        f"{nq_e} NASDAQ   : {fmt(nq)}\n"
        f"{dji_e} 다우존스 : {fmt(dji)}\n\n"
        f"🔗 <a href=\"{pages_url}\">전체 보고서 보기</a>"
    )

    resp = requests.post(
        f"https://api.telegram.org/bot{bot_token}/sendMessage",
        json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
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

    print("=" * 50)
    print(f"  📊 보고서 생성 시작: {report_date}")
    print("=" * 50)

    print("\n[1/4] 시장 데이터 수집 중...")
    market_data = get_market_data()
    print(f"  → {len(market_data)}개 종목 수집")

    print("\n[2/4] 뉴스 수집 중...")
    news = get_news()
    print(f"  → {len(news)}개 뉴스 수집")

    print("\n[3/4] Claude AI 분석 및 HTML 생성 중...")
    html_content = generate_html(market_data, news, report_date)
    os.makedirs("docs", exist_ok=True)
    with open(f"docs/{filename}", "w", encoding="utf-8") as f:
        f.write(html_content)
    print(f"  → docs/{filename} 저장 완료")

    update_index()
    print("  → docs/index.html 업데이트 완료")

    print("\n[4/4] 텔레그램 알림 전송 중...")
    pages_url = f"https://jinhae8971.github.io/gcp/{filename}"
    send_telegram(pages_url, market_data)

    print(f"\n✅ 완료! 보고서 URL: {pages_url}")


if __name__ == "__main__":
    main()
