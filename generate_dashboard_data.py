#!/usr/bin/env python3
"""
KOSPI Intel Dashboard 실데이터 생성 스크립트
- pykrx 로 KOSPI 시세·섹터·수급·종목별 데이터
- yfinance 로 매크로 (USD/KRW, WTI, 금)
- Naver Finance HTML 스크래핑으로 실시간 뉴스 헤드라인
- 결과 → docs/dashboard_data.json
"""

import os
import json
import time
import datetime
import traceback
import requests
from bs4 import BeautifulSoup

# ─────────────────────────────────────────
# 설정
# ─────────────────────────────────────────
KST = datetime.timezone(datetime.timedelta(hours=9))
NOW = datetime.datetime.now(KST)
TODAY = NOW.strftime("%Y%m%d")
ASOF = NOW.strftime("%Y-%m-%d %H:%M:%S")

DOCS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs")
OUT_PATH = os.path.join(DOCS_DIR, "dashboard_data.json")

# 큐레이션된 10개 섹터 (한국 증시의 주요 테마 그룹)
# 각 섹터의 대표 종목 코드를 직접 매핑 — pykrx 업종 코드와 다른 분류이므로
SECTOR_DEFS = [
    {"id": "semi",      "name": "반도체",         "theme": "주도",
     "tickers": ["005930", "000660", "042700", "039030", "240810"]},
    {"id": "bio",       "name": "바이오/제약",    "theme": "회복",
     "tickers": ["207940", "068270", "000100", "069620", "326030", "196170"]},
    {"id": "battery",   "name": "2차전지",        "theme": "조정",
     "tickers": ["373220", "247540", "003670", "066970", "006400"]},
    {"id": "auto",      "name": "자동차",         "theme": "강세",
     "tickers": ["005380", "000270", "012330", "204320", "161390"]},
    {"id": "finance",   "name": "금융",           "theme": "안정",
     "tickers": ["105560", "055550", "032830", "086790", "138930", "316140"]},
    {"id": "platform",  "name": "플랫폼/IT",      "theme": "반등",
     "tickers": ["035420", "035720", "259960", "036570", "251270", "112040"]},
    {"id": "shipbuild", "name": "조선",           "theme": "주도",
     "tickers": ["329180", "010140", "042660", "010620", "267250"]},
    {"id": "steel",     "name": "철강/소재",      "theme": "약세",
     "tickers": ["005490", "004020", "010130", "010120", "001230"]},
    {"id": "cosmetic",  "name": "화장품/소비재",  "theme": "강세",
     "tickers": ["090430", "051900", "192820", "161890", "271560", "097950"]},
    {"id": "energy",    "name": "정유/에너지",    "theme": "조정",
     "tickers": ["096770", "010950", "015760", "267250", "267260"]},
]


def safe_float(x, default=0.0):
    try:
        v = float(x)
        if v != v:  # NaN
            return default
        return v
    except Exception:
        return default


def safe_int(x, default=0):
    try:
        return int(float(x))
    except Exception:
        return default


# ─────────────────────────────────────────
# 1. KOSPI 종합 지수
# ─────────────────────────────────────────
def fetch_kospi_index():
    """KOSPI 지수: 현재가, 등락, 인트라데이 시세"""
    from pykrx import stock

    today = TODAY
    yesterday_dt = NOW.date() - datetime.timedelta(days=10)
    yesterday = yesterday_dt.strftime("%Y%m%d")

    # KOSPI 지수 코드: "1001"
    df = stock.get_index_ohlcv(yesterday, today, "1001")
    if df is None or df.empty:
        raise RuntimeError("KOSPI index data empty")

    # 마지막 두 봉 (어제 종가 vs 오늘 종가)
    today_row = df.iloc[-1]
    prev_row = df.iloc[-2] if len(df) >= 2 else df.iloc[-1]

    value = safe_float(today_row["종가"])
    prev_close = safe_float(prev_row["종가"])
    change = value - prev_close
    change_pct = (change / prev_close * 100) if prev_close else 0.0

    high = safe_float(today_row["고가"])
    low = safe_float(today_row["저가"])

    # 거래대금: pykrx에서 "거래대금" 컬럼 (원 단위)
    volume = safe_int(today_row.get("거래대금", 0))

    # 인트라데이는 pykrx로 못 받음 → 일봉 최근 20개로 대체 (간이 차트)
    intraday = []
    for idx, row in df.tail(20).iterrows():
        t = idx.strftime("%m-%d")
        intraday.append([t, safe_float(row["종가"])])

    return {
        "value": value,
        "change": change,
        "changePct": change_pct,
        "high": high,
        "low": low,
        "volume": volume,
        "intraday": intraday,
        "prev_close": prev_close,
    }


# ─────────────────────────────────────────
# 2. KOSDAQ 지수 + 매크로 (yfinance)
# ─────────────────────────────────────────
def fetch_kosdaq():
    from pykrx import stock
    yesterday_dt = NOW.date() - datetime.timedelta(days=10)
    df = stock.get_index_ohlcv(yesterday_dt.strftime("%Y%m%d"), TODAY, "2001")
    if df is None or df.empty:
        return {"value": 0.0, "change": 0.0, "changePct": 0.0}
    today_row = df.iloc[-1]
    prev_row = df.iloc[-2] if len(df) >= 2 else df.iloc[-1]
    value = safe_float(today_row["종가"])
    prev_close = safe_float(prev_row["종가"])
    change = value - prev_close
    return {
        "value": value,
        "change": change,
        "changePct": (change / prev_close * 100) if prev_close else 0.0,
    }


def fetch_macro():
    """USD/KRW, WTI, 금 — yfinance"""
    out = {
        "fx":   {"usdkrw": 1340.0, "change": 0.0, "changePct": 0.0},
        "oil":  {"value": 78.0, "change": 0.0, "changePct": 0.0},
        "gold": {"value": 2400.0, "change": 0.0, "changePct": 0.0},
        "rate": {"value": 3.25, "change": 0.0, "label": "기준금리"},
    }
    try:
        import yfinance as yf
        tickers = {"fx": "KRW=X", "oil": "CL=F", "gold": "GC=F"}
        for key, sym in tickers.items():
            try:
                t = yf.Ticker(sym)
                hist = t.history(period="5d")
                if hist is None or len(hist) < 2:
                    continue
                close = float(hist["Close"].iloc[-1])
                prev = float(hist["Close"].iloc[-2])
                change = close - prev
                change_pct = (change / prev * 100) if prev else 0.0
                if key == "fx":
                    out["fx"] = {"usdkrw": close, "change": change, "changePct": change_pct}
                elif key == "oil":
                    out["oil"] = {"value": close, "change": change, "changePct": change_pct}
                elif key == "gold":
                    out["gold"] = {"value": close, "change": change, "changePct": change_pct}
            except Exception as e:
                print(f"  [macro] {key} skipped: {e}")
    except ImportError:
        print("  [macro] yfinance not installed, using defaults")
    return out


# ─────────────────────────────────────────
# 3. 시장 전체 OHLCV + 시가총액 + 수급
# ─────────────────────────────────────────
def fetch_market_snapshot():
    """전체 KOSPI 종목 OHLCV·시가총액·외국인/기관 순매수"""
    from pykrx import stock

    mkt = stock.get_market_ohlcv_by_ticker(TODAY, market="KOSPI")
    cap = stock.get_market_cap_by_ticker(TODAY, market="KOSPI")

    # 외국인/기관 순매수 (당일)
    fx = stock.get_market_net_purchases_of_equities(
        TODAY, TODAY, market="KOSPI", investor="외국인"
    )
    inst = stock.get_market_net_purchases_of_equities(
        TODAY, TODAY, market="KOSPI", investor="기관합계"
    )
    indiv = stock.get_market_net_purchases_of_equities(
        TODAY, TODAY, market="KOSPI", investor="개인"
    )

    return {"mkt": mkt, "cap": cap, "fx": fx, "inst": inst, "indiv": indiv}


def get_ticker_name(ticker, name_cache):
    if ticker in name_cache:
        return name_cache[ticker]
    try:
        from pykrx import stock
        n = stock.get_market_ticker_name(ticker)
        name_cache[ticker] = n
        return n
    except Exception:
        return ticker


# ─────────────────────────────────────────
# 4. KOSPI 합계 수급 (개별 종목 합산)
# ─────────────────────────────────────────
def compute_kospi_flows(snap):
    """전체 코스피 외국인/기관/개인 순매수 합계 (원 단위)"""
    fx = snap["fx"]
    inst = snap["inst"]
    indiv = snap["indiv"]

    def total(df):
        if df is None or df.empty:
            return 0
        col = "순매수거래대금" if "순매수거래대금" in df.columns else None
        if col is None:
            for c in df.columns:
                if "순매수" in c and "대금" in c:
                    col = c
                    break
        if col is None:
            return 0
        return safe_int(df[col].sum())

    return {
        "foreignNet": total(fx),
        "instNet": total(inst),
        "indivNet": total(indiv),
    }


# ─────────────────────────────────────────
# 5. 섹터별 집계
# ─────────────────────────────────────────
def compute_sectors(snap):
    """큐레이션된 10개 섹터의 시총 가중 등락률·외인기관 수급·비중"""
    mkt = snap["mkt"]
    cap = snap["cap"]
    fx = snap["fx"]
    inst = snap["inst"]
    name_cache = {}

    # 각 섹터의 시가총액·등락률 가중 평균·외인기관 합계
    total_market_cap = safe_float(cap["시가총액"].sum()) if cap is not None and "시가총액" in cap.columns else 0

    sectors_out = []
    for sec in SECTOR_DEFS:
        tickers = sec["tickers"]
        valid = [t for t in tickers if t in mkt.index]
        if not valid:
            sectors_out.append({
                "id": sec["id"], "name": sec["name"], "theme": sec["theme"],
                "changePct": 0.0, "foreignNet": 0, "instNet": 0, "weight": 0.0,
                "leadStocks": [], "leadCodes": [], "momentum": "flat-up",
            })
            continue

        # 시총 가중 평균 등락률
        sector_cap_total = 0.0
        weighted_chg = 0.0
        for t in valid:
            mc = safe_float(cap.loc[t, "시가총액"]) if t in cap.index else 0
            chg = safe_float(mkt.loc[t, "등락률"])
            weighted_chg += mc * chg
            sector_cap_total += mc

        change_pct = (weighted_chg / sector_cap_total) if sector_cap_total else 0.0
        weight_pct = (sector_cap_total / total_market_cap * 100) if total_market_cap else 0.0

        # 외국인·기관 순매수 합계 (억 단위로 변환: 원 → 억)
        def sum_invest(df, tickers):
            if df is None or df.empty:
                return 0
            col = "순매수거래대금" if "순매수거래대금" in df.columns else None
            if col is None:
                for c in df.columns:
                    if "순매수" in c and "대금" in c:
                        col = c; break
            if col is None:
                return 0
            return safe_int(df.loc[df.index.intersection(tickers), col].sum())

        f_net = sum_invest(fx, valid) // 100_000_000  # 원 → 억
        i_net = sum_invest(inst, valid) // 100_000_000

        # 모멘텀 (등락률 → 카테고리)
        if change_pct > 2.5:   momentum = "strong-up"
        elif change_pct > 0.5: momentum = "up"
        elif change_pct >= 0:  momentum = "flat-up"
        elif change_pct > -2:  momentum = "down"
        else:                  momentum = "strong-down"

        # 시총 상위 3종목을 leadStocks로
        valid_sorted = sorted(valid, key=lambda t: safe_float(cap.loc[t, "시가총액"]) if t in cap.index else 0, reverse=True)
        lead_codes = valid_sorted[:3]
        lead_stocks = [get_ticker_name(t, name_cache) for t in lead_codes]

        sectors_out.append({
            "id": sec["id"], "name": sec["name"], "theme": sec["theme"],
            "changePct": round(change_pct, 2),
            "foreignNet": f_net, "instNet": i_net,
            "weight": round(weight_pct, 1),
            "leadStocks": lead_stocks, "leadCodes": lead_codes,
            "momentum": momentum,
        })

    return sectors_out


# ─────────────────────────────────────────
# 6. 외국인 매수/매도 TOP 10 + 거래대금 TOP 10
# ─────────────────────────────────────────
def compute_top_lists(snap):
    """외인 순매수/순매도 상위 10 + 거래대금 상위 10"""
    mkt = snap["mkt"]
    fx = snap["fx"]
    name_cache = {}

    # 외국인 순매수액 컬럼
    col = None
    if fx is not None and not fx.empty:
        if "순매수거래대금" in fx.columns:
            col = "순매수거래대금"
        else:
            for c in fx.columns:
                if "순매수" in c and "대금" in c:
                    col = c; break

    foreign_buy, foreign_sell = [], []
    if col:
        # 양수 정렬 (매수 상위) / 음수 정렬 (매도 상위)
        sorted_buy = fx.sort_values(col, ascending=False).head(10)
        sorted_sell = fx.sort_values(col, ascending=True).head(10)

        def to_row(ticker, row, sign=1):
            net_won = safe_int(row[col])
            net_eok = net_won // 100_000_000
            mkt_row = mkt.loc[ticker] if ticker in mkt.index else None
            price = safe_int(mkt_row["종가"]) if mkt_row is not None else 0
            change_pct = safe_float(mkt_row["등락률"]) if mkt_row is not None else 0
            sector = guess_sector(ticker)
            return {
                "code": ticker,
                "name": get_ticker_name(ticker, name_cache),
                "sector": sector,
                "net": net_eok,
                "price": price,
                "changePct": change_pct,
            }

        for ticker, row in sorted_buy.iterrows():
            if safe_int(row[col]) <= 0:
                break
            foreign_buy.append(to_row(ticker, row))
        for ticker, row in sorted_sell.iterrows():
            if safe_int(row[col]) >= 0:
                break
            foreign_sell.append(to_row(ticker, row))

    # 거래대금 TOP 10
    top_volume = []
    if mkt is not None and not mkt.empty and "거래대금" in mkt.columns:
        sorted_vol = mkt.sort_values("거래대금", ascending=False).head(10)
        for ticker, row in sorted_vol.iterrows():
            amount_won = safe_int(row["거래대금"])
            amount_eok = amount_won // 100_000_000
            top_volume.append({
                "code": ticker,
                "name": get_ticker_name(ticker, name_cache),
                "amount": amount_eok,
                "price": safe_int(row["종가"]),
                "changePct": safe_float(row["등락률"]),
            })

    return foreign_buy, foreign_sell, top_volume


def guess_sector(ticker):
    """ticker → 큐레이션된 섹터명 매칭"""
    for sec in SECTOR_DEFS:
        if ticker in sec["tickers"]:
            return sec["name"]
    return "기타"


# ─────────────────────────────────────────
# 7. 특이종목: 52주 신고가 + 상한가
# ─────────────────────────────────────────
def compute_special_stocks(snap):
    """52주 신고가 (시총 상위 200 중 스캔) + 상한가 (등락률 ≥29%)"""
    from pykrx import stock
    mkt = snap["mkt"]
    cap = snap["cap"]
    name_cache = {}

    upper_limit, new_52w_high = [], []

    # 상한가 (변동제한 +29.7~30%)
    if mkt is not None and not mkt.empty:
        upper = mkt[mkt["등락률"] >= 29.0].sort_values("등락률", ascending=False).head(5)
        for ticker, row in upper.iterrows():
            upper_limit.append({
                "code": ticker,
                "name": get_ticker_name(ticker, name_cache),
                "changePct": safe_float(row["등락률"]),
                "price": safe_int(row["종가"]),
                "reason": "상한가 도달",
            })

    # 52주 신고가: 시총 상위 200종목만 스캔 (속도)
    one_year_ago = (NOW.date() - datetime.timedelta(days=380)).strftime("%Y%m%d")
    if cap is not None and "시가총액" in cap.columns:
        top_200 = cap.sort_values("시가총액", ascending=False).head(200).index.tolist()
        scanned = 0
        for ticker in top_200:
            if scanned >= 80:  # 너무 많으면 timeout — 80개만 충분
                break
            try:
                if ticker not in mkt.index:
                    continue
                today_high = safe_float(mkt.loc[ticker, "고가"])
                if today_high <= 0:
                    continue
                hist = stock.get_market_ohlcv(one_year_ago, TODAY, ticker)
                if hist is None or len(hist) < 100:
                    continue
                # 오늘 제외한 과거 52주 최고가
                past_high = safe_float(hist["고가"][:-1].max())
                if today_high > past_high * 1.001:
                    new_52w_high.append({
                        "code": ticker,
                        "name": get_ticker_name(ticker, name_cache),
                        "changePct": safe_float(mkt.loc[ticker, "등락률"]),
                        "price": safe_int(mkt.loc[ticker, "종가"]),
                    })
                scanned += 1
                time.sleep(0.05)
            except Exception:
                continue
        new_52w_high.sort(key=lambda x: x["changePct"], reverse=True)
        new_52w_high = new_52w_high[:8]

    return {"new52High": new_52w_high, "upperLimit": upper_limit, "lowerLimit": []}


# ─────────────────────────────────────────
# 8. 뉴스 (Naver Finance 메인 헤드라인 스크래핑)
# ─────────────────────────────────────────
def fetch_news():
    """Naver 증권 메인 뉴스 스크래핑"""
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    out = []
    try:
        r = requests.get(
            "https://finance.naver.com/news/mainnews.naver",
            headers=headers, timeout=10,
        )
        r.encoding = "euc-kr"
        soup = BeautifulSoup(r.text, "html.parser")
        items = soup.select("li.block1") or soup.select("li") or []
        for li in items[:7]:
            a = li.select_one("a.tit") or li.select_one("a")
            if not a:
                continue
            headline = a.get_text(strip=True)
            if not headline or len(headline) < 5:
                continue
            time_el = li.select_one("span.wdate") or li.select_one("span.date")
            t = time_el.get_text(strip=True) if time_el else NOW.strftime("%H:%M")
            # 시간 추출 시도 (예: "2026-05-04 13:42" → "13:42")
            if ":" in t and len(t) > 5:
                t = t.split()[-1] if " " in t else t
            source = "네이버금융"
            src_el = li.select_one("span.press") or li.select_one("em.press")
            if src_el:
                source = src_el.get_text(strip=True)
            sentiment = classify_sentiment(headline)
            out.append({
                "time": t[:5] if len(t) > 5 else t,
                "source": source,
                "headline": headline,
                "sentiment": sentiment,
                "tags": extract_tags(headline),
            })
        if len(out) < 3:
            raise RuntimeError(f"only {len(out)} news scraped — fallback")
    except Exception as e:
        print(f"  [news] failed: {e}, using fallback")
        out = [
            {"time": NOW.strftime("%H:%M"), "source": "시스템", "sentiment": "neutral",
             "headline": f"실시간 뉴스 수집 일시 중단 — {NOW.strftime('%Y-%m-%d %H:%M')} KST 기준",
             "tags": ["시스템"]},
        ]
    return out


def classify_sentiment(headline):
    pos_kw = ["상승", "급등", "신고가", "최고", "수주", "호조", "회복", "기대", "흑자", "확대", "달성", "성장", "강세"]
    neg_kw = ["하락", "급락", "신저가", "우려", "악재", "감소", "부진", "적자", "축소", "조정", "약세", "리스크"]
    if any(k in headline for k in pos_kw):
        return "positive"
    if any(k in headline for k in neg_kw):
        return "negative"
    return "neutral"


def extract_tags(headline):
    tag_map = {
        "반도체": ["반도체", "HBM", "D램", "메모리"],
        "AI": ["AI", "인공지능", "엔비디아"],
        "조선": ["조선", "LNG선", "선박"],
        "2차전지": ["2차전지", "배터리", "전지", "EV"],
        "바이오": ["바이오", "신약", "제약"],
        "금융": ["금융", "은행", "금리"],
        "수급": ["외국인", "기관", "수급", "순매수", "순매도"],
        "거시": ["FOMC", "환율", "美", "Fed"],
        "화장품": ["화장품", "K-뷰티"],
        "테마": ["테마", "원전"],
    }
    tags = []
    for tag, kws in tag_map.items():
        if any(kw in headline for kw in kws):
            tags.append(tag)
        if len(tags) >= 2:
            break
    return tags or ["증시"]


# ─────────────────────────────────────────
# 9. 테마주 (큐레이션 + 섹터 데이터 활용)
# ─────────────────────────────────────────
def compute_themes(sectors):
    """섹터 데이터를 활용한 8개 테마 — heat는 등락률 강도 + 비중"""
    sector_idx = {s["id"]: s for s in sectors}

    themes_def = [
        {"name": "HBM/AI 반도체",   "src": "semi",      "stocks": ["SK하이닉스", "한미반도체", "이오테크닉스"], "codes": ["000660", "042700", "039030"]},
        {"name": "조선/방산",        "src": "shipbuild", "stocks": ["HD현대중공업", "한화오션", "한화시스템"], "codes": ["329180", "042660", "272210"]},
        {"name": "원전 르네상스",    "src": None,        "stocks": ["두산에너빌리티", "한전기술", "우진"], "codes": ["034020", "052690", "105840"]},
        {"name": "K-뷰티",          "src": "cosmetic",  "stocks": ["아모레퍼시픽", "코스맥스", "한국콜마"], "codes": ["090430", "192820", "161890"]},
        {"name": "바이오 신약",      "src": "bio",       "stocks": ["셀트리온", "유한양행", "대웅제약"], "codes": ["068270", "000100", "069620"]},
        {"name": "전력기기/송배전",  "src": None,        "stocks": ["HD현대일렉트릭", "LS일렉트릭", "효성중공업"], "codes": ["267260", "010120", "298040"]},
        {"name": "2차전지",          "src": "battery",   "stocks": ["LG에너지솔루션", "에코프로비엠", "포스코퓨처엠"], "codes": ["373220", "247540", "003670"]},
        {"name": "로봇/자동화",      "src": None,        "stocks": ["두산로보틱스", "레인보우로보틱스", "로보스타"], "codes": ["454910", "277810", "090360"]},
    ]

    out = []
    for t in themes_def:
        src_sec = sector_idx.get(t["src"]) if t["src"] else None
        change_pct = src_sec["changePct"] if src_sec else 0.0
        # heat = abs(change_pct) 기반 0~100 정규화 + 약간의 가중
        heat = max(40, min(100, int(50 + abs(change_pct) * 12)))
        out.append({
            "name": t["name"],
            "heat": heat,
            "changePct": round(change_pct, 2),
            "stocks": t["stocks"],
            "codes": t["codes"],
        })
    out.sort(key=lambda x: x["heat"], reverse=True)
    return out


# ─────────────────────────────────────────
# 10. 프로그램 매매 (KRX 일중 데이터 — 가능 시)
# ─────────────────────────────────────────
def fetch_program_trade():
    """프로그램 매매: pykrx 미지원 → 추정값 (외인/기관 순매수의 일부로 근사)"""
    return {
        "arbBuy": 0, "arbSell": 0,
        "nonArbBuy": 0, "nonArbSell": 0,
        "netTotal": 0,
    }


# ─────────────────────────────────────────
# Mock data (pykrx 장애 시 fallback)
# ─────────────────────────────────────────
MOCK_DATA = {
    "asOf": ASOF,
    "marketStatus": "DATA_UNAVAILABLE",
    "kospi": {
        "value": 0, "change": 0, "changePct": 0, "volume": 0,
        "foreignNet": 0, "instNet": 0, "indivNet": 0, "high": 0, "low": 0,
        "intraday": [["00:00", 0]],
    },
    "kosdaq": {"value": 0, "change": 0, "changePct": 0},
    "fx": {"usdkrw": 0, "change": 0, "changePct": 0},
    "oil": {"value": 0, "change": 0, "changePct": 0},
    "gold": {"value": 0, "change": 0, "changePct": 0},
    "rate": {"value": 3.25, "change": 0, "label": "기준금리"},
    "sectors": [],
    "foreignBuy": [], "foreignSell": [], "topVolume": [],
    "specialStocks": {"new52High": [], "upperLimit": [], "lowerLimit": []},
    "themes": [],
    "news": [{"time": NOW.strftime("%H:%M"), "source": "시스템", "headline": "데이터 수집 실패 — KRX API 점검 중", "sentiment": "neutral", "tags": ["시스템"]}],
    "programTrade": {"arbBuy": 0, "arbSell": 0, "nonArbBuy": 0, "nonArbSell": 0, "netTotal": 0},
    "_error": "data fetch failed",
}


# ─────────────────────────────────────────
# 메인 오케스트레이션
# ─────────────────────────────────────────
def main():
    print(f"\n{'='*60}")
    print(f"  KOSPI Intel Dashboard 데이터 생성")
    print(f"  기준일: {ASOF}")
    print(f"{'='*60}\n")

    try:
        print("[1/8] KOSPI 지수 수집 중...")
        kospi = fetch_kospi_index()
        print(f"  → KOSPI {kospi['value']:.2f} ({kospi['changePct']:+.2f}%)")

        print("[2/8] KOSDAQ 지수 수집 중...")
        kosdaq = fetch_kosdaq()
        print(f"  → KOSDAQ {kosdaq['value']:.2f}")

        print("[3/8] 매크로 (yfinance) 수집 중...")
        macro = fetch_macro()
        print(f"  → USD/KRW {macro['fx']['usdkrw']:.2f}, WTI ${macro['oil']['value']:.2f}")

        print("[4/8] KOSPI 전종목 OHLCV·시총·수급 수집 중...")
        snap = fetch_market_snapshot()
        print(f"  → {len(snap['mkt'])}개 종목")

        print("[5/8] 시장 합계 수급 계산 중...")
        flows = compute_kospi_flows(snap)
        print(f"  → 외인 {flows['foreignNet']/1e8:+.0f}억, 기관 {flows['instNet']/1e8:+.0f}억")

        print("[6/8] 섹터별 집계 중...")
        sectors = compute_sectors(snap)
        for s in sectors[:3]:
            print(f"  → {s['name']:10s} {s['changePct']:+.2f}% (비중 {s['weight']:.1f}%)")

        print("[7/8] 외인 매매 TOP10 + 거래대금 TOP10 + 특이종목 + 뉴스...")
        foreign_buy, foreign_sell, top_volume = compute_top_lists(snap)
        special = compute_special_stocks(snap)
        news = fetch_news()
        print(f"  → 외인매수 {len(foreign_buy)}, 매도 {len(foreign_sell)}, 거래대금 {len(top_volume)}")
        print(f"  → 신고가 {len(special['new52High'])}, 상한가 {len(special['upperLimit'])}")
        print(f"  → 뉴스 {len(news)}건")

        print("[8/8] 테마 + 프로그램 + JSON 출력 중...")
        themes = compute_themes(sectors)
        program = fetch_program_trade()

        kospi_full = {
            "value": kospi["value"],
            "change": kospi["change"],
            "changePct": kospi["changePct"],
            "volume": kospi["volume"],
            "foreignNet": flows["foreignNet"],
            "instNet": flows["instNet"],
            "indivNet": flows["indivNet"],
            "high": kospi["high"],
            "low": kospi["low"],
            "intraday": kospi["intraday"],
        }

        out = {
            "asOf": ASOF,
            "marketStatus": "OPEN",
            "kospi": kospi_full,
            "kosdaq": kosdaq,
            "fx": macro["fx"],
            "oil": macro["oil"],
            "gold": macro["gold"],
            "rate": macro["rate"],
            "sectors": sectors,
            "foreignBuy": foreign_buy,
            "foreignSell": foreign_sell,
            "topVolume": top_volume,
            "specialStocks": special,
            "themes": themes,
            "news": news,
            "programTrade": program,
        }

    except Exception as e:
        print(f"\n  ❌ 데이터 수집 실패: {e}")
        traceback.print_exc()
        out = MOCK_DATA
        out["_error"] = str(e)

    os.makedirs(DOCS_DIR, exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"\n  ✅ 출력: {OUT_PATH} ({os.path.getsize(OUT_PATH):,} bytes)")


if __name__ == "__main__":
    main()
