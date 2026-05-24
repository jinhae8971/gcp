#!/usr/bin/env python3
"""전략테스터 백테스트용 실데이터 생성기.

KOSPI / KOSPI200 / KOSDAQ 일봉 OHLCV(2014-01-01 ~ 오늘)를 받아
``docs/strategy_tester_data.json`` 으로 저장한다.

데이터 소스
  1) Naver siseJson  — 키 불필요, 기본 (레포의 dashboard 생성기와 동일 엔드포인트)
  2) pykrx           — (1) 이 부족할 때 폴백 (CI 에 설치됨)

서버 없이 GitHub Actions(또는 로컬)에서 1일 1회 실행해 docs/ 에 커밋한다.
프론트(전략테스터.html)는 이 JSON 이 없으면 자동으로 모의 데이터로 폴백한다.
"""
from __future__ import annotations

import datetime
import json
import os
import re
import sys
import time

import requests

DOCS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs")
OUT = os.path.join(DOCS, "strategy_tester_data.json")
START = "2014-01-01"
NOW = datetime.datetime.now()

NAVER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0",
    "Accept": "application/json,text/plain,*/*",
    "Referer": "https://finance.naver.com/",
}

# 프론트 코드 -> (Naver 심볼 후보, pykrx 지수코드)
SYMBOLS = {
    "KOSPI":    (["KOSPI"],              "1001"),
    "KOSPI200": (["KPI200", "KOSPI200"], "1028"),
    "KOSDAQ":   (["KOSDAQ"],             "2001"),
}


def _f(x, default=0.0):
    """'27,450' / 27450 / None 등을 안전하게 float 로."""
    try:
        v = float(str(x).replace(",", ""))
        return default if v != v else v  # NaN 방어
    except (TypeError, ValueError):
        return default


def parse_sisejson(text):
    """Naver siseJson(day) 응답(JS 배열 텍스트) -> [{date,open,high,low,close,volume}].

    응답 예: [["날짜","시가","고가","저가","종가","거래량",...],
              ["20140102", 1980, 1990, 1975, 1985, 300000000, ...], ...]
    순수 함수 — 네트워크 없이 단위 테스트 가능.
    """
    txt = (text or "").strip()
    if not txt:
        return []
    txt = re.sub(r"'([^']*)'", r'"\1"', txt)  # 작은따옴표 -> JSON 호환
    try:
        arr = json.loads(txt)
    except json.JSONDecodeError:
        return []
    if not isinstance(arr, list) or len(arr) < 2:
        return []
    out = []
    for row in arr[1:]:  # row[0] = 헤더
        if not isinstance(row, list) or len(row) < 5:
            continue
        ds = str(row[0]).strip()
        if len(ds) != 8 or not ds.isdigit():
            continue
        close = _f(row[4])
        if close <= 0:
            continue
        out.append({
            "date": f"{ds[0:4]}-{ds[4:6]}-{ds[6:8]}",
            "open": round(_f(row[1]) or close, 2),
            "high": round(_f(row[2]) or close, 2),
            "low": round(_f(row[3]) or close, 2),
            "close": round(close, 2),
            "volume": int(_f(row[5])) if len(row) > 5 else 0,
        })
    return out


def fetch_naver(symbol, start, end):
    """siseJson 을 ~400일 창으로 끊어 받아 합친다 (장기 구간 안전)."""
    rows = []
    win = datetime.timedelta(days=400)
    cur = datetime.datetime.strptime(start, "%Y-%m-%d")
    endd = datetime.datetime.strptime(end, "%Y-%m-%d")
    while cur <= endd:
        chunk_end = min(cur + win, endd)
        url = (
            "https://api.finance.naver.com/siseJson.naver"
            f"?symbol={symbol}&requestType=1"
            f"&startTime={cur:%Y%m%d}&endTime={chunk_end:%Y%m%d}&timeframe=day"
        )
        try:
            r = requests.get(url, headers=NAVER_HEADERS, timeout=12)
            if r.status_code == 200:
                rows.extend(parse_sisejson(r.text))
            else:
                print(f"  [naver] {symbol} {cur:%Y%m%d}: HTTP {r.status_code}")
        except requests.RequestException as e:
            print(f"  [naver] {symbol} {cur:%Y%m%d} 실패: {e}")
        cur = chunk_end + datetime.timedelta(days=1)
        time.sleep(0.3)
    return rows


def fetch_pykrx(code, start, end):
    """pykrx 폴백 — get_index_ohlcv (컬럼: 시가/고가/저가/종가/거래량)."""
    try:
        from pykrx import stock
    except ImportError:
        return []
    try:
        df = stock.get_index_ohlcv(start.replace("-", ""), end.replace("-", ""), code)
    except Exception as e:  # pykrx 내부 예외가 다양함
        print(f"  [pykrx] {code} 실패: {e}")
        return []
    out = []
    for idx, r in df.iterrows():
        close = _f(r.get("종가"))
        if close <= 0:
            continue
        out.append({
            "date": idx.strftime("%Y-%m-%d"),
            "open": round(_f(r.get("시가")) or close, 2),
            "high": round(_f(r.get("고가")) or close, 2),
            "low": round(_f(r.get("저가")) or close, 2),
            "close": round(close, 2),
            "volume": int(_f(r.get("거래량"))),
        })
    return out


def dedupe_sort(rows):
    by_date = {r["date"]: r for r in rows}
    return [by_date[d] for d in sorted(by_date)]


def build_series(code, start, end):
    naver_syms, pykrx_code = SYMBOLS[code]
    rows, provider = [], None
    for sym in naver_syms:
        rows = fetch_naver(sym, start, end)
        if len(rows) > 200:
            provider = f"naver:{sym}"
            break
    if len(rows) <= 200:  # Naver 부족 -> pykrx 폴백
        pk = fetch_pykrx(pykrx_code, start, end)
        if len(pk) > len(rows):
            rows, provider = pk, f"pykrx:{pykrx_code}"
    rows = dedupe_sort(rows)
    print(f"  {code}: {len(rows)} rows via {provider or 'NONE'}")
    return rows, provider


def main():
    end = NOW.strftime("%Y-%m-%d")
    universe, providers = {}, {}
    for code in SYMBOLS:
        rows, provider = build_series(code, START, end)
        if len(rows) < 200:
            print(f"✗ {code}: 데이터 부족({len(rows)}행) — 중단 (기존 JSON 유지)")
            sys.exit(1)
        universe[code] = rows
        providers[code] = provider

    starts = [u[0]["date"] for u in universe.values()]
    ends = [u[-1]["date"] for u in universe.values()]
    payload = {
        "meta": {
            "source": "KRX · Naver siseJson",
            "providers": providers,
            "generated": NOW.strftime("%Y-%m-%dT%H:%M:%S"),
            "start": min(starts),
            "end": max(ends),
            "counts": {k: len(v) for k, v in universe.items()},
        },
    }
    payload.update(universe)

    os.makedirs(DOCS, exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
    size = os.path.getsize(OUT)
    print(f"✓ {OUT}  ({size / 1024:.0f} KB)  {payload['meta']['start']}~{payload['meta']['end']}")


if __name__ == "__main__":
    main()
