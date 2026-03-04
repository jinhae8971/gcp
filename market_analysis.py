#!/usr/bin/env python3
"""
코스피 + 코스닥 장기 하락추세선 돌파 + 강한 거래량 통합 분석
- 강한 거래량: 오늘 거래량 > 20일 평균 거래량 × 2배
- 섹터/업종 정보 포함
- HTML 보고서 생성 → docs/market_trend_YYYYMMDD.html
"""

import os
import time
import datetime
import requests
import numpy as np
from pykrx import stock
from scipy.signal import find_peaks
from scipy.stats import linregress

KST        = datetime.timezone(datetime.timedelta(hours=9))
_NOW_KST   = datetime.datetime.now(KST)
TODAY      = _NOW_KST.strftime("%Y%m%d")
TODAY_KR   = _NOW_KST.strftime("%Y년 %m월 %d일")
GEN_TIME   = _NOW_KST.strftime("%H:%M KST")  # 데이터 생성 시각 (장중/장마감 확인용)
_HOUR_KST  = _NOW_KST.hour
DATA_LABEL = "📌 장마감 확정가" if _HOUR_KST >= 16 else f"⚡ 장중 실시간 ({GEN_TIME})"
START_6M   = (_NOW_KST.date() - datetime.timedelta(days=183)).strftime("%Y%m%d")
START_30D  = (_NOW_KST.date() - datetime.timedelta(days=40)).strftime("%Y%m%d")
DOCS_DIR   = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs")
HTML_OUT   = os.path.join(DOCS_DIR, f"market_trend_{TODAY}.html")


# ──────────────────────────────────────────────
# 데이터 수집
# ──────────────────────────────────────────────

def get_sector_map(today: str, market: str) -> dict:
    """업종 맵 {ticker: sector_name} — KRX 장애 시 빈 dict 반환"""
    try:
        df = stock.get_market_sector_classifications(today, market=market)
        if df.empty:
            return {}
        if "업종명" in df.columns:
            return {str(idx): str(row["업종명"]) for idx, row in df.iterrows()}
        str_cols = [c for c in df.columns if df[c].dtype == object and c != "종목명"]
        if str_cols:
            return {str(idx): str(row[str_cols[0]]) for idx, row in df.iterrows()}
        return {}
    except Exception:
        return {}


def check_breakout(ticker: str, today_close: float):
    """
    하락추세선 돌파 + 강한 거래량 체크
    Returns: (breakout, trendline, slope, peak_cnt, today_vol, avg_vol)
    """
    try:
        df = stock.get_market_ohlcv(START_6M, TODAY, ticker)
        if df is None or len(df) < 30:
            return False, 0, 0, 0, 0, 0

        # 컬럼명 호환 처리
        if "고가" not in df.columns:
            rename = {}
            for c in df.columns:
                cl = c.lower().strip()
                if cl in ("high", "고가"):
                    rename[c] = "고가"
                elif cl in ("volume", "vol", "거래량"):
                    rename[c] = "거래량"
            if rename:
                df = df.rename(columns=rename)
        if "고가" not in df.columns or "거래량" not in df.columns:
            return False, 0, 0, 0, 0, 0

        highs = df["고가"].values
        vols  = df["거래량"].values
        n     = len(highs)

        today_vol = int(vols[-1])
        past_vols = vols[:-1][-20:] if len(vols) > 1 else vols
        avg_vol   = float(np.mean(past_vols)) if len(past_vols) > 0 else 0

        # 최근 4개월(~80거래일) 고점 탐색
        peaks, _ = find_peaks(highs, distance=5, prominence=highs.mean() * 0.01)
        recent   = peaks[peaks >= max(0, n - 80)]
        if len(recent) < 2:
            return False, 0, 0, len(recent), today_vol, avg_vol

        slope, intercept, *_ = linregress(recent.astype(float), highs[recent])
        if slope >= 0:
            return False, 0, slope, len(recent), today_vol, avg_vol

        # 추세 하락폭 3% 이상
        decline = (highs[recent[0]] - highs[recent[-1]]) / highs[recent[0]] * 100
        if decline < 3.0:
            return False, 0, slope, len(recent), today_vol, avg_vol

        trendline = slope * (n - 1) + intercept
        breakout  = today_close > trendline * 1.005
        return breakout, trendline, slope, len(recent), today_vol, avg_vol

    except Exception:
        return False, 0, 0, 0, 0, 0


def _naver_rising_stocks(market: str) -> list:
    """Naver Finance API로 상승 종목 수집 (KRX API 장애 대비)"""
    mkt = "KOSPI" if market == "KOSPI" else "KOSDAQ"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 Chrome/124.0.0.0"
        ),
    }
    all_stocks = []
    for page in range(1, 20):
        url = f"https://m.stock.naver.com/api/stocks/up/{mkt}?page={page}&pageSize=100"
        try:
            resp = requests.get(url, headers=headers, timeout=10)
            if resp.status_code != 200 or not resp.text.strip():
                break
            data = resp.json()
            stocks = data.get("stocks", [])
            if not stocks:
                break
            all_stocks.extend(stocks)
            time.sleep(0.2)
        except Exception:
            break
    return all_stocks


def _parse_naver_int(s):
    """'27,450' → 27450"""
    if isinstance(s, (int, float)):
        return int(s)
    return int(str(s).replace(",", "").strip()) if s else 0


def run_market(market: str, label: str, top_n: int = 600):
    print(f"\n{'─'*50}")
    print(f"  [{label}] 분석 시작")
    print(f"{'─'*50}")

    # ── 1단계: KRX API 시도 → 실패 시 Naver API로 자동 전환
    use_naver = False
    try:
        mkt_df = stock.get_market_ohlcv_by_ticker(TODAY, market=market)
        if mkt_df.empty or "등락률" not in mkt_df.columns:
            raise KeyError("빈 데이터 또는 컬럼 누락")
        up_df = mkt_df[(mkt_df["등락률"] > 0) & (mkt_df["거래량"] > 5000)]
        total_count = len(mkt_df)
        print(f"  [KRX] 전체 {total_count}종목 → 상승 필터 {len(up_df)}종목")
    except Exception as e:
        print(f"  [KRX] 실패: {e}")
        print(f"  [Naver] 대체 데이터 수집 중...")
        use_naver = True
        naver_stocks = _naver_rising_stocks(market)
        total_count = len(naver_stocks)
        print(f"  [Naver] 상승 종목 {total_count}개 수집 완료")

    sector_map = get_sector_map(TODAY, market)

    # ── 2단계: 상위 종목 추출
    if use_naver:
        # Naver 데이터를 정렬 (등락률 기준 내림차순, 이미 정렬됨)
        candidates = []
        for s in naver_stocks[:top_n]:
            vol = _parse_naver_int(s.get("accumulatedTradingVolume", "0"))
            pct = float(s.get("fluctuationsRatio", "0"))
            if vol < 5000 or pct <= 0:
                continue
            candidates.append({
                "ticker":    s["itemCode"],
                "name":      s["stockName"],
                "close":     _parse_naver_int(s.get("closePrice", "0")),
                "change_pct": pct,
                "volume_raw": vol,
            })
        print(f"  필터 후 {len(candidates)}종목 → 상위 {top_n}개 분석")
    else:
        top_df = up_df.nlargest(top_n, "등락률")
        candidates = []
        for ticker, row in top_df.iterrows():
            candidates.append({
                "ticker":    ticker,
                "name":      "",
                "close":     int(row["종가"]),
                "change_pct": row["등락률"],
                "volume_raw": int(row["거래량"]),
            })

    # ── 3단계: 추세 돌파 분석 (pykrx Naver 백엔드 - 정상 작동)
    results = []
    for i, c in enumerate(candidates, 1):
        if i % 100 == 0:
            print(f"  ... {i}/{len(candidates)} 처리 중")

        ok, trendline, slope, peak_cnt, tv, avg_vol = check_breakout(
            c["ticker"], c["close"]
        )
        if not ok:
            continue

        vol_ratio = tv / avg_vol if avg_vol > 0 else 1.0
        if vol_ratio < 2.0:
            continue

        name = c["name"] or stock.get_market_ticker_name(c["ticker"])
        sector = sector_map.get(c["ticker"], "기타")

        results.append({
            "ticker":     c["ticker"],
            "name":       name,
            "close":      c["close"],
            "change_pct": c["change_pct"],
            "volume":     tv,
            "avg_vol":    avg_vol,
            "vol_ratio":  vol_ratio,
            "peak_cnt":   peak_cnt,
            "sector":     sector,
        })

    results.sort(key=lambda x: x["change_pct"], reverse=True)
    for i, r in enumerate(results):
        r["rank"] = i + 1

    print(f"  → 최종 선별: {len(results)}개 (상위 10개 사용)")
    return results


# ──────────────────────────────────────────────
# HTML 생성
# ──────────────────────────────────────────────

def _rows_html(items: list, max_rows: int = 10) -> str:
    html = ""
    for r in items[:max_rows]:
        up    = r["change_pct"] > 0
        cc    = "#3fb950" if up else "#f85149"
        vhigh = r["vol_ratio"] >= 5
        vc    = "#e3b341" if vhigh else "#58a6ff"
        vbg   = "#2a2a1a" if vhigh else "#1a2233"
        naver_url = f"https://finance.naver.com/item/main.naver?code={r['ticker']}"
        html += f"""
        <tr>
          <td class="td-rank">{r['rank']}</td>
          <td class="td-name">
            <a class="sname" href="{naver_url}" target="_blank" rel="noopener">{r['name']}</a>
            <div class="scode">{r['ticker']}</div>
          </td>
          <td class="td-price">{r['close']:,}원</td>
          <td class="td-change" style="color:{cc};">{r['change_pct']:+.2f}%</td>
          <td class="td-vol">{r['volume']:,}</td>
          <td class="td-ratio">
            <span class="vbadge" style="background:{vbg};color:{vc};border:1px solid {vc}40;">
              {r['vol_ratio']:.1f}×
            </span>
          </td>
          <td class="td-sector">{r['sector']}</td>
        </tr>"""
    return html


def _table_card(market_label: str, icon: str, color: str, results: list, analyzed: int) -> str:
    found    = len(results)
    top_chg  = f"{results[0]['change_pct']:+.1f}%" if results else "N/A"
    top_vol  = f"{results[0]['vol_ratio']:.1f}×"   if results else "N/A"
    rows     = _rows_html(results)
    empty    = f'<tr><td colspan="7" style="text-align:center;color:#484f58;padding:28px;">조건 충족 종목 없음</td></tr>' if not results else ""

    return f"""
<div class="market-card" style="border-top:3px solid {color};">
  <div class="mcard-header">
    <div>
      <div class="mcard-title">{icon} {market_label}</div>
      <div class="mcard-sub">분석 {analyzed:,}개 → 선별 <b style="color:{color};">{found}개</b></div>
    </div>
    <div class="mcard-stats">
      <div class="mstat"><div class="mstat-val" style="color:{color};">{found}</div><div class="mstat-lbl">선별 종목</div></div>
      <div class="mstat"><div class="mstat-val" style="color:#3fb950;">{top_chg}</div><div class="mstat-lbl">최고 등락률</div></div>
      <div class="mstat"><div class="mstat-val" style="color:#e3b341;">{top_vol}</div><div class="mstat-lbl">최고 거래량배율</div></div>
    </div>
  </div>
  <div class="table-wrap">
    <table>
      <thead>
        <tr>
          <th>#</th><th>종목명</th><th>종가</th><th>등락률</th>
          <th>거래량</th><th>배율</th><th>섹터/업종</th>
        </tr>
      </thead>
      <tbody>{rows}{empty}</tbody>
    </table>
  </div>
</div>"""


def generate_html(kospi: list, kospi_n: int, kosdaq: list, kosdaq_n: int) -> str:
    kospi_card  = _table_card("코스피", "🏛️", "#e3b341", kospi,  kospi_n)
    kosdaq_card = _table_card("코스닥", "📈", "#58a6ff", kosdaq, kosdaq_n)

    total_found      = len(kospi) + len(kosdaq)
    kospi_top_vol    = f"{kospi[0]['vol_ratio']:.1f}×"  if kospi  else "N/A"
    kosdaq_top_vol   = f"{kosdaq[0]['vol_ratio']:.1f}×" if kosdaq else "N/A"

    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>📉➡️📈 코스피·코스닥 하락추세 돌파 | {TODAY_KR}</title>
  <style>
    *{{box-sizing:border-box;margin:0;padding:0;}}
    body{{
      font-family:'Segoe UI','Noto Sans KR',Arial,sans-serif;
      background:#0d1117;color:#c9d1d9;min-height:100vh;padding:24px 16px;
    }}

    /* ── 헤더 ── */
    .header{{border-bottom:1px solid #30363d;padding-bottom:18px;margin-bottom:22px;}}
    .header h1{{font-size:1.4rem;color:#58a6ff;}}
    .header p{{font-size:0.84rem;color:#8b949e;margin-top:6px;line-height:1.5;}}
    .header-meta{{font-size:0.76rem;color:#484f58;margin-top:5px;}}

    /* ── 요약 배너 ── */
    .summary-row{{
      display:grid;
      grid-template-columns:repeat(auto-fit,minmax(130px,1fr));
      gap:10px;margin-bottom:22px;
    }}
    .scard{{
      background:#161b22;border:1px solid #30363d;border-radius:9px;
      padding:14px;text-align:center;
    }}
    .scard .val{{font-size:1.7rem;font-weight:700;}}
    .scard .lbl{{font-size:0.74rem;color:#8b949e;margin-top:5px;}}
    .c-blue{{color:#58a6ff;}} .c-yellow{{color:#e3b341;}}
    .c-green{{color:#3fb950;}} .c-red{{color:#f85149;}}

    /* ── 조건 박스 ── */
    .cond-box{{
      background:#161b22;border:1px solid #388bfd33;border-radius:9px;
      padding:14px;margin-bottom:22px;
    }}
    .cond-box h3{{font-size:0.88rem;color:#58a6ff;margin-bottom:8px;}}
    .cond-item{{display:flex;gap:8px;font-size:0.8rem;color:#c9d1d9;padding:3px 0;}}
    .cond-item .dot{{color:#3fb950;flex-shrink:0;font-weight:700;}}

    /* ── 시장 카드 ── */
    .markets-grid{{
      display:grid;
      grid-template-columns:repeat(auto-fit,minmax(340px,1fr));
      gap:16px;
    }}
    .market-card{{
      background:#161b22;border:1px solid #30363d;border-radius:10px;
      overflow:hidden;
    }}
    .mcard-header{{
      display:flex;align-items:flex-start;justify-content:space-between;
      flex-wrap:wrap;gap:12px;padding:16px 18px;
      border-bottom:1px solid #21262d;
    }}
    .mcard-title{{font-size:1.05rem;font-weight:700;color:#c9d1d9;}}
    .mcard-sub{{font-size:0.78rem;color:#8b949e;margin-top:4px;}}
    .mcard-stats{{display:flex;gap:16px;flex-wrap:wrap;}}
    .mstat{{text-align:center;}}
    .mstat-val{{font-size:1.2rem;font-weight:700;}}
    .mstat-lbl{{font-size:0.7rem;color:#8b949e;margin-top:2px;}}

    /* ── 테이블 ── */
    .table-wrap{{overflow-x:auto;}}
    table{{width:100%;border-collapse:collapse;}}
    thead{{background:#0d1117;}}
    th{{
      padding:9px 8px;font-size:0.74rem;color:#8b949e;
      text-align:center;font-weight:600;white-space:nowrap;
      border-bottom:1px solid #21262d;
    }}
    td{{
      padding:9px 8px;font-size:0.82rem;
      border-bottom:1px solid #161b22;text-align:center;vertical-align:middle;
    }}
    tr:last-child td{{border-bottom:none;}}
    tr:hover td{{background:#1c2128;}}

    .td-rank{{color:#8b949e;font-weight:700;font-size:0.85rem;}}
    .td-name{{text-align:left;}}
    .sname{{font-weight:600;color:#c9d1d9;text-decoration:none;display:block;}}
    .sname:hover{{color:#58a6ff;text-decoration:underline;}}
    .scode{{font-size:0.69rem;color:#8b949e;margin-top:2px;}}
    .td-price{{font-family:monospace;white-space:nowrap;}}
    .td-change{{font-weight:700;font-family:monospace;white-space:nowrap;}}
    .td-vol{{font-size:0.76rem;color:#8b949e;font-family:monospace;white-space:nowrap;}}
    .vbadge{{
      display:inline-block;padding:2px 7px;border-radius:10px;
      font-size:0.75rem;font-weight:700;white-space:nowrap;
    }}
    .td-sector{{font-size:0.74rem;color:#8b949e;}}

    /* ── 공통 탭 UI ── */
    .tab-bar{{
      display:flex;gap:4px;padding:10px 14px 0;
      border-bottom:1px solid #21262d;
    }}
    .tab-btn{{
      padding:6px 14px;font-size:0.8rem;border:none;cursor:pointer;
      border-radius:6px 6px 0 0;background:transparent;color:#8b949e;
      font-weight:600;transition:all .15s;
    }}
    .tab-btn.active{{background:#21262d;color:#c9d1d9;}}
    .tab-content{{display:none;}}
    .tab-content.active{{display:block;}}

    /* ── 면책 & 푸터 ── */
    .disclaimer{{
      background:#161b22;border:1px solid #30363d;border-radius:8px;
      padding:12px;margin-top:22px;font-size:0.75rem;color:#8b949e;line-height:1.6;
    }}
    .footer{{text-align:center;margin-top:18px;color:#484f58;font-size:0.73rem;}}
    .footer a{{color:#58a6ff;text-decoration:none;}}

    @media(max-width:600px){{
      .header h1{{font-size:1.1rem;}}
      .mcard-header{{flex-direction:column;}}
      .mstat-val{{font-size:1rem;}}
    }}
  </style>
</head>
<body>

<!-- 헤더 -->
<div class="header">
  <h1>📉➡️📈 코스피·코스닥 하락추세 돌파 종목</h1>
  <p>6개월 이상 지속된 하락 추세선을 <b>강한 거래량</b>과 함께 돌파한 종목 분석</p>
  <div class="header-meta">기준일: {TODAY_KR} | 코스피 {kospi_n:,}개 + 코스닥 {kosdaq_n:,}개 분석 | <span style="color:#{'3fb950' if _HOUR_KST >= 16 else 'e3b341'};">{DATA_LABEL}</span></div>
</div>

<!-- 요약 -->
<div class="summary-row">
  <div class="scard"><div class="val c-yellow">{len(kospi)}</div><div class="lbl">🏛️ 코스피 선별</div></div>
  <div class="scard"><div class="val c-blue">{len(kosdaq)}</div><div class="lbl">📈 코스닥 선별</div></div>
  <div class="scard"><div class="val c-green">{total_found}</div><div class="lbl">✅ 전체 합산</div></div>
  <div class="scard"><div class="val c-yellow">{kospi_top_vol}</div><div class="lbl">🏛️ 코스피 최고배율</div></div>
  <div class="scard"><div class="val c-blue">{kosdaq_top_vol}</div><div class="lbl">📈 코스닥 최고배율</div></div>
</div>

<!-- 조건 -->
<div class="cond-box">
  <h3>🔍 선별 조건 (코스피·코스닥 공통)</h3>
  <div class="cond-item"><span class="dot">①</span><span><b>하락추세 돌파</b>: 최근 4개월(~80거래일) 고점 추세선이 하향(-3% 이상) 이며, 오늘 종가가 추세선 대비 0.5% 이상 상향 돌파</span></div>
  <div class="cond-item"><span class="dot">②</span><span><b>강한 거래량 동반</b>: 오늘 거래량 ≥ 20일 평균 거래량 × 2배 (돌파 신뢰도 확인)</span></div>
  <div class="cond-item"><span class="dot">③</span><span><b>당일 상승 마감</b>: 등락률 > 0 &amp; 최소 거래량 5,000주 이상</span></div>
</div>

<!-- 시장 카드 -->
<div class="markets-grid">
  {kospi_card}
  {kosdaq_card}
</div>

<div class="disclaimer">
  ⚠️ <b>투자 유의사항</b>: 본 분석은 기술적 지표 기반 자동 생성 정보이며, 투자 권유가 아닙니다.
  주식 투자에는 원금 손실 위험이 있으며, 모든 투자 결정은 본인 판단과 책임 하에 이루어져야 합니다.
  추세 돌파는 상승을 보장하지 않으며 시장 상황에 따라 다를 수 있습니다.
</div>

<div class="footer">
  🤖 비서 윈터 자동 분석 · {TODAY_KR} ·
  <a href="dashboard.html">대시보드</a> ·
  <a href="index.html">보고서 목록</a>
</div>

</body>
</html>"""


# ──────────────────────────────────────────────
# 메인
# ──────────────────────────────────────────────

def send_error_telegram(error_msg: str):
    """pykrx 장애 시 텔레그램 알림"""
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id   = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not bot_token or not chat_id:
        return
    text = (
        f"⚠️ 코스피·코스닥 추세 돌파 분석 실패\n\n"
        f"📅 {TODAY_KR} {GEN_TIME}\n"
        f"원인: {error_msg}\n\n"
        f"KRX 데이터 API 장애로 분석이 불가합니다.\n"
        f"API 정상화 시 자동 재개됩니다."
    )
    try:
        import requests as _req
        _req.post(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            json={"chat_id": chat_id, "text": text},
            timeout=10,
        )
    except Exception:
        pass


def main():
    print(f"\n{'='*60}")
    print(f"  📉➡️📈 코스피·코스닥 하락추세 돌파 + 강한 거래량 분석")
    print(f"  기준일: {TODAY}")
    print(f"{'='*60}")

    try:
        kospi_results  = run_market("KOSPI",  "코스피", top_n=400)
        kosdaq_results = run_market("KOSDAQ", "코스닥", top_n=600)
    except (KeyError, ValueError, TypeError) as e:
        error_msg = f"pykrx 데이터 수집 실패: {e}"
        print(f"\n  ❌ {error_msg}")
        print("  → KRX API 장애 또는 컬럼 구조 변경 감지")
        send_error_telegram(error_msg)
        print("  → 텔레그램 장애 알림 전송 완료")
        return

    kospi_n  = 400
    kosdaq_n = 600

    print(f"\n{'='*60}")
    print(f"  최종 결과: 코스피 {len(kospi_results)}개 / 코스닥 {len(kosdaq_results)}개")
    print(f"{'='*60}")

    # 코스피 상위 10 출력
    print("\n🏛️ 코스피 TOP10")
    print(f"{'순위':<4} {'종목명':<14} {'코드':<7} {'종가':>8} {'등락률':>8} {'배율':>7} {'섹터'}")
    for r in kospi_results[:10]:
        print(f"{r['rank']:<4} {r['name']:<14} {r['ticker']:<7} {r['close']:>8,} {r['change_pct']:>+7.2f}% {r['vol_ratio']:>6.1f}× {r['sector']}")

    # 코스닥 상위 10 출력
    print("\n📈 코스닥 TOP10")
    print(f"{'순위':<4} {'종목명':<14} {'코드':<7} {'종가':>8} {'등락률':>8} {'배율':>7} {'섹터'}")
    for r in kosdaq_results[:10]:
        print(f"{r['rank']:<4} {r['name']:<14} {r['ticker']:<7} {r['close']:>8,} {r['change_pct']:>+7.2f}% {r['vol_ratio']:>6.1f}× {r['sector']}")

    # HTML 생성
    print(f"\n[HTML 생성] {HTML_OUT}")
    html = generate_html(kospi_results, kospi_n, kosdaq_results, kosdaq_n)
    os.makedirs(DOCS_DIR, exist_ok=True)
    with open(HTML_OUT, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"  → 완료 ({len(html):,} bytes)")

    # 항상 최신 파일로 덮어쓰기 (고정 URL: market_trend_latest.html)
    LATEST_OUT = os.path.join(DOCS_DIR, "market_trend_latest.html")
    with open(LATEST_OUT, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"  → 최신 고정 URL 업데이트: market_trend_latest.html")


if __name__ == "__main__":
    main()
