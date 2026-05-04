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
# Naver Finance Mobile API (KRX 로그인 불필요)
# ─────────────────────────────────────────
NAVER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0",
    "Accept": "application/json",
}

_NAVER_LOGGED_KEYS = {"index": False, "stock_list": False, "stock_basic": False, "intraday": False}
_NAVER_RAW_SAMPLES = {}  # key -> dict (첫 번째 raw response sample for embedding in JSON debug)

def _parse_naver_num(v, default=0):
    """Naver는 숫자를 string('27,450') 또는 int로 반환 — 둘 다 처리"""
    if v is None:
        return default
    if isinstance(v, (int, float)):
        return v
    s = str(v).replace(",", "").strip()
    if not s or s == "-":
        return default
    try:
        return float(s)
    except Exception:
        return default

def _first_present(d, keys, default=0):
    """여러 후보 키 중 첫 존재하는 값을 숫자로 파싱"""
    for k in keys:
        if k in d and d[k] not in (None, "", "-"):
            return _parse_naver_num(d[k], default)
    return default


def naver_index_basic(market="KOSPI"):
    """Naver: KOSPI/KOSDAQ 인덱스 기본 시세"""
    try:
        url = f"https://m.stock.naver.com/api/index/{market}/basic"
        r = requests.get(url, headers=NAVER_HEADERS, timeout=10)
        r.raise_for_status()
        d = r.json()
        if not _NAVER_LOGGED_KEYS["index"]:
            print(f"  [naver-debug] index raw: {json.dumps(d, ensure_ascii=False)[:600]}")
            _NAVER_RAW_SAMPLES["index_kospi"] = d
            _NAVER_LOGGED_KEYS["index"] = True
        return {
            "value":     _first_present(d, ["closePrice", "lastPrice", "currentPrice"]),
            "change":    _first_present(d, ["compareToPreviousClosePrice", "compareToPreviousPrice", "change"]),
            "changePct": _first_present(d, ["fluctuationsRatio", "changeRate", "fluctuationRate"]),
            "high":      _first_present(d, ["highPrice", "high"]),
            "low":       _first_present(d, ["lowPrice", "low"]),
            "volume":    _first_present(d, ["accumulatedTradingValue", "tradingValue", "tradeAmount", "accumulatedTradingVolume"]),
        }
    except Exception as e:
        print(f"  [naver-index] {market} failed: {e}")
        return None


def naver_stock_basic(code):
    """Naver: 개별 종목 기본 시세 (등락률·종가)"""
    try:
        url = f"https://m.stock.naver.com/api/stocks/{code}/basic"
        r = requests.get(url, headers=NAVER_HEADERS, timeout=8)
        r.raise_for_status()
        d = r.json()
        if not _NAVER_LOGGED_KEYS["stock_basic"]:
            print(f"  [naver-debug] stock_basic raw: {json.dumps(d, ensure_ascii=False)[:800]}")
            _NAVER_RAW_SAMPLES["stock_basic"] = d
            _NAVER_LOGGED_KEYS["stock_basic"] = True
        return {
            "code": code,
            "name":      d.get("stockName") or d.get("itemName") or d.get("name") or code,
            "price":     int(_first_present(d, ["closePrice", "lastPrice", "currentPrice"])),
            "changePct": _first_present(d, ["fluctuationsRatio", "changeRate", "fluctuationRate"]),
            "change":    _first_present(d, ["compareToPreviousClosePrice", "compareToPreviousPrice", "change"]),
            "volume_won": int(_first_present(d, ["accumulatedTradingValue", "tradingValue", "tradeAmount"])),
            "volume":    int(_first_present(d, ["accumulatedTradingVolume", "tradingVolume"])),
            "marketCap": int(_first_present(d, ["marketValue", "marketCap", "marketValueAmount"])),
        }
    except Exception as e:
        print(f"  [naver-stock-basic] {code} failed: {e}")
        return None


def naver_index_intraday(market="KOSPI"):
    """Naver: 인덱스 일봉 차트 (최근 30일)"""
    try:
        url = f"https://m.stock.naver.com/api/chart/domestic/index/{market}?periodType=dayCandle&count=30"
        r = requests.get(url, headers=NAVER_HEADERS, timeout=10)
        r.raise_for_status()
        d = r.json()
        out = []
        for row in d:
            t = row.get("localTime", "")[5:10]  # MM-DD
            close = safe_float(row.get("closePrice", 0))
            out.append([t, close])
        return out[-20:]
    except Exception as e:
        print(f"  [naver-intraday] {market} failed: {e}")
        return None


def naver_top_stocks(market="KOSPI", direction="up", limit=30):
    """Naver: 상승/하락 상위 종목 (페이지당 100개씩)"""
    try:
        url = f"https://m.stock.naver.com/api/stocks/{direction}/{market}?page=1&pageSize=100"
        r = requests.get(url, headers=NAVER_HEADERS, timeout=10)
        r.raise_for_status()
        d = r.json()
        stocks = d.get("stocks", [])
        if stocks and not _NAVER_LOGGED_KEYS["stock_list"]:
            print(f"  [naver-debug] stock_list[0] raw: {json.dumps(stocks[0], ensure_ascii=False)[:600]}")
            _NAVER_RAW_SAMPLES["stock_list_first"] = stocks[0]
            _NAVER_LOGGED_KEYS["stock_list"] = True
        out = []
        for s in stocks[:limit]:
            out.append({
                "code": s.get("itemCode") or s.get("code", ""),
                "name": s.get("stockName") or s.get("name", ""),
                "price":     int(_first_present(s, ["closePrice", "lastPrice"])),
                "changePct": _first_present(s, ["fluctuationsRatio", "changeRate"]),
                "volume_won": int(_first_present(s, ["accumulatedTradingValue", "tradingValue", "tradeAmount"])),
                "volume":     int(_first_present(s, ["accumulatedTradingVolume", "tradingVolume"])),
            })
        return out
    except Exception as e:
        print(f"  [naver-top] {direction} failed: {e}")
        return []


def naver_stock_integration(code):
    """Naver: 개별 종목 상세 (외인 보유율 등)"""
    try:
        url = f"https://m.stock.naver.com/api/stocks/{code}/integration"
        r = requests.get(url, headers=NAVER_HEADERS, timeout=8)
        r.raise_for_status()
        return r.json()
    except Exception:
        return None


# ─────────────────────────────────────────
# 1. KOSPI 종합 지수
# ─────────────────────────────────────────
def fetch_kospi_index():
    """KOSPI 지수: pykrx 우선, 실패 시 Naver 폴백"""
    # 1차 시도: pykrx
    try:
        from pykrx import stock
        today = TODAY
        yesterday_dt = NOW.date() - datetime.timedelta(days=10)
        yesterday = yesterday_dt.strftime("%Y%m%d")
        df = stock.get_index_ohlcv(yesterday, today, "1001")
        if df is None or df.empty:
            raise RuntimeError("KOSPI index data empty")

        today_row = df.iloc[-1]
        prev_row = df.iloc[-2] if len(df) >= 2 else df.iloc[-1]
        value = safe_float(today_row["종가"])
        prev_close = safe_float(prev_row["종가"])
        change = value - prev_close
        change_pct = (change / prev_close * 100) if prev_close else 0.0
        intraday = [[idx.strftime("%m-%d"), safe_float(row["종가"])] for idx, row in df.tail(20).iterrows()]
        return {
            "value": value, "change": change, "changePct": change_pct,
            "high": safe_float(today_row["고가"]),
            "low": safe_float(today_row["저가"]),
            "volume": safe_int(today_row.get("거래대금", 0)),
            "intraday": intraday, "prev_close": prev_close,
            "_source": "pykrx",
        }
    except Exception as e:
        print(f"  [kospi-index] pykrx failed: {e} → Naver fallback")

    # 2차 시도: Naver
    basic = naver_index_basic("KOSPI")
    if not basic or basic["value"] == 0:
        raise RuntimeError("KOSPI index unavailable from both pykrx and Naver")
    intraday = naver_index_intraday("KOSPI") or [["", basic["value"]]]
    return {
        "value": basic["value"],
        "change": basic["change"],
        "changePct": basic["changePct"],
        "high": basic["high"],
        "low": basic["low"],
        "volume": basic["volume"],
        "intraday": intraday,
        "prev_close": basic["value"] - basic["change"],
        "_source": "naver",
    }


# ─────────────────────────────────────────
# 2. KOSDAQ 지수 + 매크로 (yfinance)
# ─────────────────────────────────────────
def fetch_kosdaq():
    """KOSDAQ 지수: pykrx 우선, 실패 시 Naver"""
    try:
        from pykrx import stock
        yesterday_dt = NOW.date() - datetime.timedelta(days=10)
        df = stock.get_index_ohlcv(yesterday_dt.strftime("%Y%m%d"), TODAY, "2001")
        if df is None or df.empty:
            raise RuntimeError("kosdaq empty")
        today_row = df.iloc[-1]
        prev_row = df.iloc[-2] if len(df) >= 2 else df.iloc[-1]
        value = safe_float(today_row["종가"])
        prev_close = safe_float(prev_row["종가"])
        change = value - prev_close
        return {
            "value": value, "change": change,
            "changePct": (change / prev_close * 100) if prev_close else 0.0,
        }
    except Exception:
        basic = naver_index_basic("KOSDAQ")
        if basic:
            return {"value": basic["value"], "change": basic["change"], "changePct": basic["changePct"]}
        return {"value": 0.0, "change": 0.0, "changePct": 0.0}


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
# Naver-only fallback path (when KRX login is unavailable)
# ─────────────────────────────────────────
def naver_only_pipeline():
    """KRX 없이 Naver Mobile API만으로 가능한 데이터 구성"""
    print("  [naver-only] KRX 우회 모드 활성")

    kospi_basic = naver_index_basic("KOSPI") or {"value": 0, "change": 0, "changePct": 0, "high": 0, "low": 0, "volume": 0}
    kospi_intra = naver_index_intraday("KOSPI") or []
    kosdaq_basic = naver_index_basic("KOSDAQ") or {"value": 0, "change": 0, "changePct": 0}

    # 상승/하락 상위 (등락률 기준)
    rising = naver_top_stocks("KOSPI", "up", limit=50)
    falling = naver_top_stocks("KOSPI", "down", limit=50)
    all_stocks = rising + falling

    # 큐레이션 섹터의 모든 ticker → 일부는 TOP에 없을 수 있으므로 개별 페치
    code_data = {s["code"]: s for s in all_stocks}
    needed = set()
    for sec in SECTOR_DEFS:
        for t in sec["tickers"]:
            if t not in code_data:
                needed.add(t)

    print(f"  [naver-only] 개별 페치 필요한 섹터 종목: {len(needed)}개")
    fetched = 0
    for code in needed:
        basic = naver_stock_basic(code)
        if basic:
            code_data[code] = basic
            fetched += 1
            time.sleep(0.05)
    print(f"  [naver-only] 개별 페치 완료: {fetched}/{len(needed)}")

    # 거래대금 상위 10 (전체 stocks + 페치 종목 합산)
    all_known = list(code_data.values())
    top_volume_raw = sorted([s for s in all_known if s.get("volume_won", 0) > 0], key=lambda x: x.get("volume_won", 0), reverse=True)[:10]
    top_volume = [{
        "code": s["code"], "name": s["name"],
        "amount": s.get("volume_won", 0) // 100_000_000,
        "price": s.get("price", 0), "changePct": s.get("changePct", 0),
    } for s in top_volume_raw]

    # 외인 수급 proxy: 거래대금 기준 상위 종목 (실제 외인 데이터 없음)
    top_gainers = sorted([s for s in rising if s.get("volume_won", 0) > 0], key=lambda x: x.get("volume_won", 0), reverse=True)[:10]
    top_losers = sorted([s for s in falling if s.get("volume_won", 0) > 0], key=lambda x: x.get("volume_won", 0), reverse=True)[:10]

    def to_flow_row(s, sign=1):
        # 거래대금의 ~5%를 외인 순매수로 추정 (proxy)
        proxy_net = max(1, (s.get("volume_won", 0) // 100_000_000) // 20) * sign
        return {
            "code": s["code"], "name": s["name"],
            "sector": guess_sector(s["code"]),
            "net": proxy_net,
            "price": s.get("price", 0), "changePct": s.get("changePct", 0),
        }

    foreign_buy = [to_flow_row(s, +1) for s in top_gainers]
    foreign_sell = [to_flow_row(s, -1) for s in top_losers]

    # 상한가 (등락률 ≥29%)
    upper_limit = [{
        "code": s["code"], "name": s["name"],
        "changePct": s["changePct"], "price": s["price"],
        "reason": "상한가 도달"
    } for s in rising if s.get("changePct", 0) >= 29.0][:5]

    # 52주 신고가 근사 (큰 폭 상승)
    new_52w_high = [{
        "code": s["code"], "name": s["name"],
        "changePct": s["changePct"], "price": s["price"],
    } for s in sorted(rising, key=lambda x: x.get("changePct", 0), reverse=True) if s.get("changePct", 0) >= 3.0][:8]

    # 섹터 집계 — 이제 모든 leadStocks 데이터가 있어야 함
    sectors_out = []
    total_market_cap = sum(s.get("marketCap", 0) for s in all_known)
    for sec in SECTOR_DEFS:
        valid = [t for t in sec["tickers"] if t in code_data]
        if not valid:
            sectors_out.append({
                "id": sec["id"], "name": sec["name"], "theme": sec["theme"],
                "changePct": 0.0, "foreignNet": 0, "instNet": 0, "weight": 0.0,
                "leadStocks": [], "leadCodes": [], "momentum": "flat-up",
            })
            continue

        # 시총 가중 평균 등락률 (시총 정보 있으면), 없으면 단순 평균
        sector_cap = sum(code_data[t].get("marketCap", 0) for t in valid)
        if sector_cap > 0:
            avg_chg = sum(code_data[t].get("marketCap", 0) * code_data[t].get("changePct", 0) for t in valid) / sector_cap
            weight = (sector_cap / total_market_cap * 100) if total_market_cap else 0
        else:
            avg_chg = sum(code_data[t].get("changePct", 0) for t in valid) / len(valid)
            sec_vol = sum(code_data[t].get("volume_won", 0) for t in valid)
            total_vol = sum(s.get("volume_won", 0) for s in all_known)
            weight = (sec_vol / total_vol * 100) if total_vol else 0

        if avg_chg > 2.5:   momentum = "strong-up"
        elif avg_chg > 0.5: momentum = "up"
        elif avg_chg >= -0.5: momentum = "flat-up"
        elif avg_chg > -2:  momentum = "down"
        else:               momentum = "strong-down"

        # 시총 상위 3종목으로 leadStocks 정렬
        valid_sorted = sorted(valid, key=lambda t: code_data[t].get("marketCap", 0) or code_data[t].get("volume_won", 0), reverse=True)
        lead_codes = valid_sorted[:3]
        lead_names = [code_data[t].get("name", t) for t in lead_codes]

        sectors_out.append({
            "id": sec["id"], "name": sec["name"], "theme": sec["theme"],
            "changePct": round(avg_chg, 2),
            "foreignNet": 0, "instNet": 0,
            "weight": round(weight, 1),
            "leadStocks": lead_names, "leadCodes": lead_codes,
            "momentum": momentum,
        })

    # KOSPI 합계 거래대금 = 모든 알려진 종목의 거래대금 합산 (근사)
    kospi_volume_won = sum(s.get("volume_won", 0) for s in all_known) * 5  # 표본 stocks → 전체 추정

    return {
        "kospi": {
            "value": kospi_basic.get("value", 0),
            "change": kospi_basic.get("change", 0),
            "changePct": kospi_basic.get("changePct", 0),
            "volume": kospi_basic.get("volume", 0) or kospi_volume_won,
            "high": kospi_basic.get("high", 0),
            "low": kospi_basic.get("low", 0),
            "foreignNet": 0, "instNet": 0, "indivNet": 0,
            "intraday": kospi_intra,
        },
        "kosdaq": kosdaq_basic,
        "sectors": sectors_out,
        "foreignBuy": foreign_buy,
        "foreignSell": foreign_sell,
        "topVolume": top_volume,
        "specialStocks": {"new52High": new_52w_high, "upperLimit": upper_limit, "lowerLimit": []},
    }


# ─────────────────────────────────────────
# 메인 오케스트레이션
# ─────────────────────────────────────────
def main():
    print(f"\n{'='*60}")
    print(f"  KOSPI Intel Dashboard 데이터 생성")
    print(f"  기준일: {ASOF}")
    print(f"{'='*60}\n")

    krx_id = os.environ.get("KRX_ID", "")
    krx_pw = os.environ.get("KRX_PW", "")
    if krx_id and krx_pw:
        print(f"  [auth] KRX 자격증명 사용 (id={krx_id[:3]}***)")
    else:
        print(f"  [auth] KRX 자격증명 없음 — pykrx 실패 시 Naver 폴백")

    macro = fetch_macro()
    print(f"  → 매크로: USD/KRW {macro['fx']['usdkrw']:.2f}, WTI ${macro['oil']['value']:.2f}")

    news = fetch_news()
    print(f"  → 뉴스 {len(news)}건")

    pipeline_source = "unknown"
    out_partial = None

    # 1차: pykrx 풀 파이프라인
    try:
        print("\n[pykrx] 풀 파이프라인 시도...")
        kospi = fetch_kospi_index()
        kosdaq = fetch_kosdaq()
        snap = fetch_market_snapshot()
        flows = compute_kospi_flows(snap)
        sectors = compute_sectors(snap)
        foreign_buy, foreign_sell, top_volume = compute_top_lists(snap)
        special = compute_special_stocks(snap)

        out_partial = {
            "kospi": {
                "value": kospi["value"], "change": kospi["change"], "changePct": kospi["changePct"],
                "volume": kospi["volume"],
                "foreignNet": flows["foreignNet"], "instNet": flows["instNet"], "indivNet": flows["indivNet"],
                "high": kospi["high"], "low": kospi["low"],
                "intraday": kospi["intraday"],
            },
            "kosdaq": kosdaq,
            "sectors": sectors,
            "foreignBuy": foreign_buy, "foreignSell": foreign_sell, "topVolume": top_volume,
            "specialStocks": special,
        }
        pipeline_source = "pykrx" if not kospi.get("_source") else f"pykrx+{kospi['_source']}"
        print(f"  ✓ pykrx 파이프라인 성공")
    except Exception as e:
        print(f"  ✗ pykrx 실패: {e}")
        traceback.print_exc()

    # 2차: Naver 폴백 (pykrx 실패 시)
    if out_partial is None:
        try:
            print("\n[naver-only] 폴백 파이프라인 시도...")
            out_partial = naver_only_pipeline()
            pipeline_source = "naver-only"
            print(f"  ✓ Naver 파이프라인 성공")
        except Exception as e:
            print(f"  ✗ Naver 폴백도 실패: {e}")
            traceback.print_exc()

    # 3차: 모두 실패 시 mock
    if out_partial is None:
        print("\n[mock] 모든 데이터 수집 실패 — mock 출력")
        out = dict(MOCK_DATA)
        out["_error"] = "all data sources failed"
        out["news"] = news
        out["asOf"] = ASOF
    else:
        themes = compute_themes(out_partial["sectors"])
        program = fetch_program_trade()
        out = {
            "asOf": ASOF,
            "marketStatus": "OPEN",
            "kospi": out_partial["kospi"],
            "kosdaq": out_partial["kosdaq"],
            "fx": macro["fx"], "oil": macro["oil"], "gold": macro["gold"], "rate": macro["rate"],
            "sectors": out_partial["sectors"],
            "foreignBuy": out_partial["foreignBuy"],
            "foreignSell": out_partial["foreignSell"],
            "topVolume": out_partial["topVolume"],
            "specialStocks": out_partial["specialStocks"],
            "themes": themes,
            "news": news,
            "programTrade": program,
            "_source": pipeline_source,
        }

    # 디버그용 raw 샘플 임베드 (필드명 발견 후 제거)
    if _NAVER_RAW_SAMPLES:
        out["_debug"] = _NAVER_RAW_SAMPLES

    os.makedirs(DOCS_DIR, exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"\n  ✅ 출력: {OUT_PATH} ({os.path.getsize(OUT_PATH):,} bytes) · source={out.get('_source', out.get('_error', '?'))}")


if __name__ == "__main__":
    main()
