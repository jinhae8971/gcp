#!/usr/bin/env python3
"""
코스닥 장기 하락추세선 돌파 + 강한 거래량 분석 스크립트
- 강한 거래량: 오늘 거래량 > 20일 평균 거래량 × 2
- 섹터/테마 정보 포함
- HTML 보고서 생성 → docs/kosdaq_YYYYMMDD.html
"""

import sys
import os
import datetime
import json
import re

import numpy as np
from pykrx import stock
from scipy.signal import find_peaks
from scipy.stats import linregress

TODAY = datetime.date.today().strftime("%Y%m%d")
START_6M = (datetime.date.today() - datetime.timedelta(days=183)).strftime("%Y%m%d")
START_30D = (datetime.date.today() - datetime.timedelta(days=40)).strftime("%Y%m%d")

HTML_OUTPUT = os.path.join(os.path.dirname(__file__), "docs", f"kosdaq_{TODAY}.html")


def get_sector_map(today: str) -> dict:
    """업종(섹터) 맵 {ticker: sector_name}
    pykrx get_market_sector_classifications: index=종목코드, columns=['종목명','업종명',...]
    """
    try:
        df = stock.get_market_sector_classifications(today, market="KOSDAQ")
        if "업종명" in df.columns:
            return {str(idx): str(row["업종명"]) for idx, row in df.iterrows()}
        # fallback: 첫 번째 문자열 컬럼
        str_cols = [c for c in df.columns if df[c].dtype == object and c != '종목명']
        if str_cols:
            col = str_cols[0]
            return {str(idx): str(row[col]) for idx, row in df.iterrows()}
        return {}
    except Exception as e:
        print(f"  ⚠️ 섹터 정보 조회 실패: {e}")
        return {}


def get_volume_avg(ticker: str, days: int = 20) -> float:
    """N일 평균 거래량"""
    try:
        df = stock.get_market_ohlcv(START_30D, TODAY, ticker)
        if df is None or len(df) < 5:
            return 0
        vols = df["거래량"].values
        # 오늘 제외한 이전 N일
        if len(vols) > 1:
            past = vols[:-1][-days:]
        else:
            return 0
        return float(np.mean(past)) if len(past) > 0 else 0
    except Exception:
        return 0


def check_downtrend_breakout(ticker_code: str, today_close: float):
    """
    하락추세선 돌파 여부 확인
    Returns: (breakout: bool, trendline_today: float, slope: float, peak_count: int, today_volume: int, avg_volume: float)
    """
    try:
        df = stock.get_market_ohlcv(START_6M, TODAY, ticker_code)
        if df is None or len(df) < 30:
            return False, 0, 0, 0, 0, 0

        highs = df["고가"].values
        vols = df["거래량"].values
        n = len(highs)

        today_volume = int(vols[-1]) if len(vols) > 0 else 0
        # 20일 평균 (오늘 제외)
        past_vols = vols[:-1][-20:] if len(vols) > 1 else vols[-20:]
        avg_volume = float(np.mean(past_vols)) if len(past_vols) > 0 else 0

        # 최근 4개월(~80거래일) 고점 탐색
        peaks, _ = find_peaks(highs, distance=5, prominence=highs.mean() * 0.01)
        recent_peaks = peaks[peaks >= max(0, n - 80)]

        if len(recent_peaks) < 2:
            return False, 0, 0, len(recent_peaks), today_volume, avg_volume

        peak_x = recent_peaks.astype(float)
        peak_y = highs[recent_peaks]

        slope, intercept, r_val, p_val, _ = linregress(peak_x, peak_y)

        if slope >= 0:
            return False, 0, slope, len(recent_peaks), today_volume, avg_volume

        # 추세 하락폭 확인 (3% 이상)
        first_peak_val = highs[recent_peaks[0]]
        last_peak_val = highs[recent_peaks[-1]]
        trend_decline_pct = (first_peak_val - last_peak_val) / first_peak_val * 100
        if trend_decline_pct < 3.0:
            return False, 0, slope, len(recent_peaks), today_volume, avg_volume

        trendline_today = slope * (n - 1) + intercept
        breakout = today_close > trendline_today * 1.005

        return breakout, trendline_today, slope, len(recent_peaks), today_volume, avg_volume

    except Exception as e:
        return False, 0, 0, 0, 0, 0


def run_analysis():
    print(f"\n{'='*60}")
    print(f"📊 코스닥 하락추세 돌파 + 강한 거래량 분석")
    print(f"{'='*60}")
    print(f"기준일: {TODAY}")

    # 1. 코스닥 전체 데이터
    print("\n[1/4] 코스닥 시장 데이터 조회 중...")
    mkt_df = stock.get_market_ohlcv_by_ticker(TODAY, market="KOSDAQ")
    total = len(mkt_df)
    print(f"  → 전체 {total}개 종목")

    # 2. 1차 필터: 상승 + 최소 거래량
    up_df = mkt_df[(mkt_df["등락률"] > 0) & (mkt_df["거래량"] > 10000)]
    print(f"  → 상승+거래량 필터: {len(up_df)}개")

    # 3. 섹터 맵 조회
    print("\n[2/4] 섹터 정보 조회 중...")
    sector_map = get_sector_map(TODAY)
    if sector_map:
        print(f"  → {len(sector_map)}개 종목 섹터 정보 로드 완료")
    else:
        print("  ⚠️ 섹터 정보 없음 — '정보 없음'으로 표시")

    # 4. 등락률 상위 600개 대상 추세 분석
    top_df = up_df.nlargest(600, "등락률")
    print(f"\n[3/4] 등락률 상위 {len(top_df)}개 추세 돌파 분석 중...")
    print("  (종목당 약 1초 소요, 잠시 기다려주세요...)")

    results = []
    checked = 0
    for ticker_code, row in top_df.iterrows():
        name = stock.get_market_ticker_name(ticker_code)
        close = row["종가"]
        change_pct = row["등락률"]
        volume = int(row["거래량"])

        breakout, trendline, slope, peak_cnt, tv, avg_vol = check_downtrend_breakout(
            ticker_code, close
        )
        checked += 1
        if checked % 50 == 0:
            print(f"  ... {checked}/{len(top_df)} 완료")

        if not breakout:
            continue

        # 강한 거래량 조건: 오늘 거래량 > 20일 평균 × 2
        if avg_vol <= 0:
            avg_vol = tv  # fallback
        vol_ratio = tv / avg_vol if avg_vol > 0 else 1.0
        if vol_ratio < 2.0:
            continue  # 강한 거래량 미충족

        sector = sector_map.get(ticker_code, "기타")

        results.append(
            {
                "rank": 0,
                "ticker": ticker_code,
                "name": name,
                "close": int(close),
                "change_pct": change_pct,
                "volume": tv,
                "avg_volume": avg_vol,
                "vol_ratio": vol_ratio,
                "trendline": trendline,
                "slope": slope,
                "peak_cnt": peak_cnt,
                "sector": sector,
            }
        )

    # 등락률 내림차순 정렬
    results.sort(key=lambda x: x["change_pct"], reverse=True)
    for i, r in enumerate(results):
        r["rank"] = i + 1

    top10 = results[:10]
    print(f"\n[4/4] 분석 완료!")
    print(f"  분석: {checked}개 | 추세 돌파: {len([r for r in results if True])}개 (강한 거래량 포함)")
    print(f"\n{'─'*70}")
    print(f"{'순위':<4} {'종목명':<16} {'코드':<8} {'종가':>7} {'등락률':>8} {'거래량':>10} {'거래량비율':>9} {'피크':>4} {'섹터'}")
    print(f"{'─'*70}")
    for r in top10:
        print(
            f"{r['rank']:<4} {r['name']:<16} {r['ticker']:<8} "
            f"{r['close']:>7,} {r['change_pct']:>+7.2f}% "
            f"{r['volume']:>10,} {r['vol_ratio']:>8.1f}배 "
            f"{r['peak_cnt']:>3}개 {r['sector']}"
        )

    return results, checked


def generate_html(results: list, total_analyzed: int) -> str:
    today_str = datetime.date.today().strftime("%Y년 %m월 %d일")
    top10 = results[:10]

    rows = ""
    for r in top10:
        change_color = "#3fb950" if r["change_pct"] > 0 else "#f85149"
        vol_badge_color = "#e3b341" if r["vol_ratio"] >= 3 else "#58a6ff"
        rows += f"""
        <tr>
          <td class="rank">{r['rank']}</td>
          <td class="name-cell">
            <div class="stock-name">{r['name']}</div>
            <div class="stock-code">{r['ticker']}</div>
          </td>
          <td class="price">{r['close']:,}원</td>
          <td class="change" style="color:{change_color};">{r['change_pct']:+.2f}%</td>
          <td class="volume">{r['volume']:,}</td>
          <td class="vol-ratio">
            <span class="vol-badge" style="background:{'#2a3a1a' if r['vol_ratio']>=3 else '#1a2a3a'};color:{vol_badge_color};border:1px solid {vol_badge_color};">
              {r['vol_ratio']:.1f}배
            </span>
          </td>
          <td class="sector">{r['sector']}</td>
          <td class="peaks">{r['peak_cnt']}개</td>
        </tr>"""

    total_found = len(results)

    html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>코스닥 하락추세 돌파 + 강한 거래량 | {today_str}</title>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      font-family: 'Segoe UI', 'Noto Sans KR', Arial, sans-serif;
      background: #0d1117;
      color: #c9d1d9;
      min-height: 100vh;
      padding: 24px 16px;
    }}
    .header {{
      border-bottom: 1px solid #30363d;
      padding-bottom: 18px; margin-bottom: 24px;
    }}
    .header h1 {{ font-size: 1.4rem; color: #58a6ff; }}
    .header p {{ font-size: 0.85rem; color: #8b949e; margin-top: 6px; }}
    .meta {{ font-size: 0.78rem; color: #484f58; margin-top: 4px; }}

    .summary-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
      gap: 12px; margin-bottom: 24px;
    }}
    .summary-card {{
      background: #161b22; border: 1px solid #30363d; border-radius: 10px;
      padding: 16px; text-align: center;
    }}
    .summary-card .value {{ font-size: 1.8rem; font-weight: 700; }}
    .summary-card .label {{ font-size: 0.78rem; color: #8b949e; margin-top: 6px; }}
    .val-blue {{ color: #58a6ff; }}
    .val-green {{ color: #3fb950; }}
    .val-yellow {{ color: #e3b341; }}

    .condition-box {{
      background: #161b22; border: 1px solid #388bfd44; border-radius: 10px;
      padding: 16px; margin-bottom: 24px;
    }}
    .condition-box h3 {{ font-size: 0.9rem; color: #58a6ff; margin-bottom: 10px; }}
    .condition-item {{
      display: flex; align-items: flex-start; gap: 8px;
      font-size: 0.82rem; color: #c9d1d9; padding: 4px 0;
    }}
    .condition-item .dot {{ color: #3fb950; font-weight: bold; flex-shrink: 0; }}

    .table-wrap {{ overflow-x: auto; }}
    table {{
      width: 100%; border-collapse: collapse;
      background: #161b22; border-radius: 10px; overflow: hidden;
      border: 1px solid #30363d;
    }}
    thead {{ background: #21262d; }}
    th {{
      padding: 12px 10px; font-size: 0.78rem; color: #8b949e;
      text-align: center; font-weight: 600; white-space: nowrap;
      border-bottom: 1px solid #30363d;
    }}
    td {{
      padding: 11px 10px; font-size: 0.85rem;
      border-bottom: 1px solid #21262d; text-align: center;
      vertical-align: middle;
    }}
    tr:last-child td {{ border-bottom: none; }}
    tr:hover td {{ background: #1c2128; }}

    .rank {{ color: #8b949e; font-size: 0.9rem; font-weight: 700; }}
    .name-cell {{ text-align: left; }}
    .stock-name {{ font-weight: 600; color: #c9d1d9; }}
    .stock-code {{ font-size: 0.72rem; color: #8b949e; margin-top: 2px; }}
    .price {{ font-family: monospace; color: #c9d1d9; }}
    .change {{ font-weight: 700; font-family: monospace; }}
    .volume {{ font-size: 0.8rem; color: #8b949e; font-family: monospace; }}
    .vol-badge {{
      display: inline-block; padding: 2px 8px; border-radius: 12px;
      font-size: 0.78rem; font-weight: 700;
    }}
    .sector {{
      font-size: 0.78rem; color: #8b949e;
      max-width: 120px; white-space: normal;
    }}
    .peaks {{ font-size: 0.78rem; color: #484f58; }}

    .disclaimer {{
      background: #161b22; border: 1px solid #30363d; border-radius: 8px;
      padding: 14px; margin-top: 24px;
      font-size: 0.78rem; color: #8b949e; line-height: 1.6;
    }}
    .footer {{
      text-align: center; margin-top: 24px;
      color: #484f58; font-size: 0.75rem;
    }}
    .footer a {{ color: #58a6ff; text-decoration: none; }}
    @media (max-width: 600px) {{
      .header h1 {{ font-size: 1.1rem; }}
      th, td {{ padding: 8px 6px; font-size: 0.75rem; }}
    }}
  </style>
</head>
<body>

<div class="header">
  <h1>📉➡️📈 코스닥 하락추세 돌파 종목 (강한 거래량 동반)</h1>
  <p>6개월 이상 하락 추세선을 돌파하고, 평균 거래량의 2배 이상 거래된 종목</p>
  <div class="meta">기준일: {today_str} | 분석 종목: {total_analyzed:,}개 | 최종 선별: {total_found}개</div>
</div>

<div class="summary-grid">
  <div class="summary-card">
    <div class="value val-blue">{total_analyzed:,}</div>
    <div class="label">📋 분석 대상</div>
  </div>
  <div class="summary-card">
    <div class="value val-green">{total_found}</div>
    <div class="label">✅ 최종 선별</div>
  </div>
  <div class="summary-card">
    <div class="value val-yellow">{top10[0]['change_pct'] if top10 else 0:+.1f}%</div>
    <div class="label">🏆 최고 등락률</div>
  </div>
  <div class="summary-card">
    <div class="value val-yellow">{top10[0]['vol_ratio'] if top10 else 0:.1f}x</div>
    <div class="label">📊 최고 거래량배율</div>
  </div>
</div>

<div class="condition-box">
  <h3>🔍 선별 조건</h3>
  <div class="condition-item">
    <span class="dot">①</span>
    <span><b>하락추세 돌파</b>: 최근 4개월(~80거래일) 고점을 연결한 추세선이 하향(-3% 이상 하락)이며, 오늘 종가가 추세선을 0.5% 이상 상향 돌파</span>
  </div>
  <div class="condition-item">
    <span class="dot">②</span>
    <span><b>강한 거래량 동반</b>: 오늘 거래량이 20일 평균 거래량의 2배 이상 (돌파 신뢰도 확인)</span>
  </div>
  <div class="condition-item">
    <span class="dot">③</span>
    <span><b>상승 마감</b>: 전일 대비 등락률 양수 + 최소 거래량 10,000주 이상</span>
  </div>
</div>

<div class="table-wrap">
<table>
  <thead>
    <tr>
      <th>순위</th>
      <th>종목명 / 코드</th>
      <th>종가</th>
      <th>등락률</th>
      <th>거래량</th>
      <th>거래량 배율</th>
      <th>섹터 / 업종</th>
      <th>피크수</th>
    </tr>
  </thead>
  <tbody>
    {rows}
  </tbody>
</table>
</div>

<div class="disclaimer">
  ⚠️ <b>투자 유의사항</b>: 본 분석은 기술적 지표를 기반으로 자동 생성된 정보이며, 투자 권유가 아닙니다.
  주식 투자에는 원금 손실 위험이 있으며, 모든 투자 결정은 본인의 판단과 책임 하에 이루어져야 합니다.
  추세선 돌파가 반드시 상승을 보장하지 않으며, 시장 환경에 따라 다를 수 있습니다.
</div>

<div class="footer">
  🤖 비서 윈터 자동 분석 · {today_str} ·
  <a href="dashboard.html">대시보드</a> ·
  <a href="index.html">보고서 목록</a>
</div>

</body>
</html>"""
    return html


def main():
    results, checked = run_analysis()

    if not results:
        print("\n⚠️ 조건을 만족하는 종목이 없습니다.")
        # 빈 HTML 생성
        results = []

    print(f"\n[HTML 생성] {HTML_OUTPUT}")
    html = generate_html(results, checked)
    os.makedirs(os.path.dirname(HTML_OUTPUT), exist_ok=True)
    with open(HTML_OUTPUT, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"  → 완료 ({len(html):,} bytes)")

    return results


if __name__ == "__main__":
    main()
