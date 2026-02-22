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
import ssl
import time
import warnings
import requests
import anthropic
import xml.etree.ElementTree as ET
from bs4 import BeautifulSoup
from datetime import datetime, timezone, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from requests.adapters import HTTPAdapter
from urllib3.util.ssl_ import create_urllib3_context

# 구형 SSL 서버(은행연합회 등) 접속을 위한 어댑터
class LegacySSLAdapter(HTTPAdapter):
    """TLSv1.2 이하 구형 서버와의 호환성 어댑터"""
    def init_poolmanager(self, *args, **kwargs):
        ctx = create_urllib3_context()
        ctx.set_ciphers("DEFAULT@SECLEVEL=1")
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        kwargs["ssl_context"] = ctx
        super().init_poolmanager(*args, **kwargs)

warnings.filterwarnings("ignore", message="Unverified HTTPS request")

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
# 1-A. 은행연합회 공식 금리공시 수집
# ──────────────────────────────────────────────
ALL_BANKS = "0010030|0013175|0011625|0010001|0010002|0013909|0010026|0010927|0010006|0014807|0010016|0010017|0010019|0010020|0010022|0010024|0014674|0015130|0017801"

def scrape_kfb() -> dict:
    """전국은행연합회 소비자포털 — 정기예금·적금 금리공시 수집"""
    result = {
        "source": "전국은행연합회 소비자포털",
        "source_url": "https://portal.kfb.or.kr/compare/receiving_deposit_3.php",
        "scraped_at": datetime.now(KST).strftime("%Y.%m.%d %H:%M"),
        "deposits": [],
        "savings": [],
    }
    session = requests.Session()
    session.mount("https://portal.kfb.or.kr", LegacySSLAdapter())

    # ── 정기예금 ──
    try:
        session.get("https://portal.kfb.or.kr/compare/receiving_deposit_3.php",
                    headers=HEADERS, timeout=10, verify=False)
        ph = dict(HEADERS)
        ph["Referer"] = "https://portal.kfb.or.kr/compare/receiving_deposit_3.php"
        ph["Content-Type"] = "application/x-www-form-urlencoded"
        resp = session.post(
            "https://portal.kfb.or.kr/compare/receiving_deposit_3_search_result.php",
            data={"InterestType": "Simple", "BankValue": ALL_BANKS,
                  "InterestMonth": "BANK_ORDER", "OrderByType": "ASC",
                  "JOIN_METHOD": "", "SortType": ""},
            headers=ph, timeout=15, verify=False,
        )
        resp.encoding = "euc-kr"
        soup = BeautifulSoup(resp.text, "html.parser")
        rows = soup.find_all("tr")
        # 헤더 2행 제외
        for row in rows[2:]:
            cells = [td.get_text(strip=True) for td in row.find_all("td")]
            if len(cells) < 3 or not cells[0].strip():
                continue
            bank, product = cells[0], cells[1]
            # 기본금리: 1개월~36개월(cells 2~7), 12개월=cells[5]
            # 최고우대금리: cells 8~13, 12개월=cells[11]
            # 전월평균: cells[-1]
            def safe(lst, i):
                try: return lst[i] if lst[i] else "-"
                except: return "-"
            result["deposits"].append({
                "bank": bank, "product": product,
                "rate_6m":  safe(cells, 4),
                "rate_12m": safe(cells, 5),
                "rate_24m": safe(cells, 6),
                "max_12m":  safe(cells, 11),
                "avg_12m":  safe(cells, -1),
            })
        print(f"  ✓ 은행연합회 정기예금: {len(result['deposits'])}개 상품")
    except Exception as e:
        print(f"  ✗ 은행연합회 정기예금: {e}")

    # ── 정액적립식 적금 ──
    try:
        session2 = requests.Session()
        session2.mount("https://portal.kfb.or.kr", LegacySSLAdapter())
        session2.get("https://portal.kfb.or.kr/compare/receiving_neosave.php",
                     headers=HEADERS, timeout=10, verify=False)
        ph2 = dict(HEADERS)
        ph2["Referer"] = "https://portal.kfb.or.kr/compare/receiving_neosave.php"
        ph2["Content-Type"] = "application/x-www-form-urlencoded"
        resp2 = session2.post(
            "https://portal.kfb.or.kr/compare/receiving_neosave_search_result.php",
            data={"InterestType1": "1", "InterestType2": "Simple",
                  "BankValue": ALL_BANKS, "InterestMonth": "BANK_ORDER",
                  "OrderByType": "ASC", "JOIN_METHOD": "", "SortType": ""},
            headers=ph2, timeout=15, verify=False,
        )
        resp2.encoding = "euc-kr"
        soup2 = BeautifulSoup(resp2.text, "html.parser")
        rows2 = soup2.find_all("tr")
        for row in rows2[2:]:
            cells = [td.get_text(strip=True) for td in row.find_all("td")]
            if len(cells) < 3 or not cells[0].strip():
                continue
            bank, product = cells[0], cells[1]
            def safe2(lst, i):
                try: return lst[i] if lst[i] else "-"
                except: return "-"
            result["savings"].append({
                "bank": bank, "product": product,
                "rate_6m":  safe2(cells, 2),
                "rate_12m": safe2(cells, 3),
                "max_12m":  safe2(cells, 7),
                "avg_12m":  safe2(cells, -1),
            })
        print(f"  ✓ 은행연합회 정액적립식 적금: {len(result['savings'])}개 상품")
    except Exception as e:
        print(f"  ✗ 은행연합회 적금: {e}")

    return result


# ──────────────────────────────────────────────
# 1-B. 공식 사이트 스크래핑 (카카오뱅크)
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
# 4-A. Python 직접 HTML 빌더 (테이블·구조 생성)
# ──────────────────────────────────────────────
def _safe_float(v):
    try: return float(v)
    except: return 0.0

def _build_deposit_table(deposits: list) -> str:
    """정기예금 비교표 HTML (12개월 기준금리 높은 순)"""
    rows = sorted(deposits, key=lambda d: _safe_float(d["rate_12m"]), reverse=True)[:15]
    tr_html = ""
    for i, d in enumerate(rows):
        bg = "#1a2744" if i % 2 == 0 else "#161b22"
        max_style = ' style="color:#3fb950;font-weight:700;"' if d["max_12m"] not in ("-", "") else ""
        tr_html += (
            f'<tr style="background:{bg};">'
            f'<td style="padding:8px 10px;white-space:nowrap;">{d["bank"]}</td>'
            f'<td style="padding:8px 10px;">{d["product"]}</td>'
            f'<td style="text-align:center;padding:8px 6px;">{d["rate_6m"]}</td>'
            f'<td style="text-align:center;padding:8px 6px;color:#58a6ff;font-weight:600;">{d["rate_12m"]}</td>'
            f'<td style="text-align:center;padding:8px 6px;">{d["rate_24m"]}</td>'
            f'<td style="text-align:center;padding:8px 6px;"{max_style}>{d["max_12m"]}</td>'
            f'<td style="text-align:center;padding:8px 6px;">{d["avg_12m"]}</td>'
            f'</tr>\n'
        )
    return (
        '<table style="width:100%;border-collapse:collapse;font-size:0.85rem;">'
        '<thead><tr style="background:#1f6feb;">'
        '<th style="padding:10px 8px;text-align:left;">은행명</th>'
        '<th style="padding:10px 8px;text-align:left;">상품명</th>'
        '<th style="padding:10px 6px;">6개월</th>'
        '<th style="padding:10px 6px;">12개월</th>'
        '<th style="padding:10px 6px;">24개월</th>'
        '<th style="padding:10px 6px;color:#3fb950;">최고금리(12개월)</th>'
        '<th style="padding:10px 6px;">전월평균</th>'
        '</tr></thead><tbody>'
        + tr_html +
        '</tbody></table>'
    )

def _build_savings_table(savings: list) -> str:
    """정액적립식 적금 비교표 HTML (12개월 기준금리 높은 순)"""
    rows = sorted(savings, key=lambda s: _safe_float(s["rate_12m"]), reverse=True)[:10]
    tr_html = ""
    for i, s in enumerate(rows):
        bg = "#1a2744" if i % 2 == 0 else "#161b22"
        max_style = ' style="color:#3fb950;font-weight:700;"' if s["max_12m"] not in ("-", "") else ""
        tr_html += (
            f'<tr style="background:{bg};">'
            f'<td style="padding:8px 10px;white-space:nowrap;">{s["bank"]}</td>'
            f'<td style="padding:8px 10px;">{s["product"]}</td>'
            f'<td style="text-align:center;padding:8px 6px;">{s["rate_6m"]}</td>'
            f'<td style="text-align:center;padding:8px 6px;color:#58a6ff;font-weight:600;">{s["rate_12m"]}</td>'
            f'<td style="text-align:center;padding:8px 6px;"{max_style}>{s["max_12m"]}</td>'
            f'<td style="text-align:center;padding:8px 6px;">{s["avg_12m"]}</td>'
            f'</tr>\n'
        )
    return (
        '<table style="width:100%;border-collapse:collapse;font-size:0.85rem;">'
        '<thead><tr style="background:#1f6feb;">'
        '<th style="padding:10px 8px;text-align:left;">은행명</th>'
        '<th style="padding:10px 8px;text-align:left;">상품명</th>'
        '<th style="padding:10px 6px;">6개월</th>'
        '<th style="padding:10px 6px;">12개월</th>'
        '<th style="padding:10px 6px;color:#3fb950;">최고금리(12개월)</th>'
        '<th style="padding:10px 6px;">전월평균</th>'
        '</tr></thead><tbody>'
        + tr_html +
        '</tbody></table>'
    )

def _build_news_section(news: dict) -> str:
    """신규 상품 + 일반 뉴스 기사 HTML 카드"""
    card_style = (
        'style="background:#161b22;border:1px solid #30363d;border-radius:8px;'
        'padding:14px 16px;margin-bottom:12px;"'
    )
    btn_style = (
        'style="display:inline-block;background:#21262d;color:#58a6ff;'
        'font-size:0.78rem;padding:4px 10px;border-radius:6px;'
        'text-decoration:none;margin-top:8px;" target="_blank"'
    )
    out = ""
    all_items = news["new_products"] + news["general_finance"][:8]
    for n in all_items:
        tag = '<span style="background:#e3b341;color:#000;font-size:0.7rem;padding:2px 6px;border-radius:4px;margin-right:6px;font-weight:700;">신규</span>' if n["is_new_prod"] else ""
        link_btn = f'<a href="{n["link"]}" {btn_style}>[기사 원문 보기]</a>' if n.get("link_ok") else ""
        out += (
            f'<div {card_style}>'
            f'<div style="font-size:0.8rem;color:#8b949e;margin-bottom:4px;">{tag}{n["source"]} · {n.get("pub","")[:20]}</div>'
            f'<div style="font-weight:600;margin-bottom:6px;">{n["title"]}</div>'
            f'<div style="font-size:0.85rem;color:#8b949e;">{n["desc"][:200]}</div>'
            f'{link_btn}'
            f'</div>\n'
        )
    if not out:
        out = '<p style="color:#8b949e;">이번 주 수집된 기사가 없습니다.</p>'
    return out

def _build_refs_section(news: dict) -> str:
    """하단 출처 링크 섹션"""
    btn = (
        'style="display:inline-block;background:#21262d;color:#58a6ff;'
        'font-size:0.78rem;padding:4px 10px;border-radius:6px;'
        'text-decoration:none;margin:3px;" target="_blank"'
    )
    out = ""
    for n in news["new_products"] + news["general_finance"]:
        if n.get("link_ok"):
            out += f'<a href="{n["link"]}" {btn}>[{n["source"]}] {n["title"][:50]}…</a>\n'
    for name, url in VERIFY_URLS:
        out += f'<a href="{url}" {btn}>{name}</a>\n'
    return out


# ──────────────────────────────────────────────
# 4-B. Claude AI — 서론·뉴스 분석·큐레이션만 생성
# ──────────────────────────────────────────────
def _claude_editorial(kfb: dict, kakao: dict, news: dict, report_date: str, week_str: str) -> dict:
    """Claude가 서론·뉴스분석·큐레이션 HTML 조각만 생성 (~3000 토큰)"""
    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))

    # 핵심 데이터 요약 (상위만 전달)
    top_deps = sorted(kfb["deposits"], key=lambda d: _safe_float(d["rate_12m"]), reverse=True)[:8]
    top_savs = sorted(kfb["savings"], key=lambda s: _safe_float(s["rate_12m"]), reverse=True)[:5]
    top_max  = sorted(kfb["deposits"], key=lambda d: _safe_float(d["max_12m"]), reverse=True)[:5]
    top_24m  = sorted(kfb["deposits"], key=lambda d: _safe_float(d["rate_24m"]), reverse=True)[:4]
    top_6m   = sorted(kfb["deposits"], key=lambda d: _safe_float(d["rate_6m"]),  reverse=True)[:4]

    def d_line(d): return f'{d["bank"]} {d["product"]} — 기본12개월:{d["rate_12m"]}%, 최고:{d["max_12m"]}%, 24개월:{d.get("rate_24m","-")}%, 6개월:{d.get("rate_6m","-")}%'
    def s_line(s): return f'{s["bank"]} {s["product"]} — 기본12개월:{s["rate_12m"]}%, 최고:{s["max_12m"]}%'

    dep_summary  = "\n".join(d_line(d) for d in top_deps)
    sav_summary  = "\n".join(s_line(s) for s in top_savs)
    max_summary  = "\n".join(d_line(d) for d in top_max)
    long_summary = "\n".join(d_line(d) for d in top_24m)
    park_summary = "\n".join(d_line(d) for d in top_6m)

    kakao_rates = ""
    for p in kakao["products"]:
        kakao_rates += f'{p["name"]}: {" | ".join(p["rates"][:4])}\n'

    news_brief = "\n".join(
        f'[{n["source"]}] {n["title"]} — {n["desc"][:100]}'
        for n in (news["new_products"] + news["general_finance"])[:10]
    )

    prompt = f"""당신은 친절한 금융 블로거 "비서 윈터"입니다. 오늘은 {report_date}입니다.

아래 데이터를 바탕으로 HTML 조각(fragment) 3개를 작성하세요.
반드시 JSON 형식 {{ "intro": "...", "news_analysis": "...", "curation": "..." }} 으로만 출력하세요.
(마크다운 코드블록 없이, 순수 JSON만)

━━━━━ 금리 데이터 (출처: 전국은행연합회 공시 {kfb["scraped_at"]} 기준) ━━━━━
◆ 정기예금 상위 8개 (12개월 기준금리순):
{dep_summary}

◆ 최고우대금리 상위 5개 (12개월):
{max_summary}

◆ 장기예금 상위 4개 (24개월 기준):
{long_summary}

◆ 단기예금 상위 4개 (6개월 기준, 파킹용):
{park_summary}

◆ 적금 상위 5개 (12개월):
{sav_summary}

◆ 카카오뱅크:
{kakao_rates}

━━━━━ 이번 주 뉴스 ━━━━━
{news_brief}

━━━━━ 작성 지침 ━━━━━
팩트 규칙: 위 데이터에 없는 금리 수치 절대 금지. 금리 사용 시 "(출처: 전국은행연합회 공시, {kfb["scraped_at"]} 기준)" 표기.

[intro] — 이번 주 금리 시장 서론 HTML 3~4문단
  • 다크 테마 스타일 (<p style="...">)
  • 뉴스와 글로벌 배경을 자연스럽게 연결
  • 친근한 블로그 말투

[news_analysis] — 시중은행 동향 HTML
  • 뉴스 기사에서 언급된 은행·금리·상품 동향 분석 2~3문단
  • 기사 출처 언급 시 텍스트로만 (링크 버튼은 Python이 별도 추가)

[curation] — 주제별 추천 상품 큐레이션 HTML
  • 제목: <h2 style="color:#f0883e;border-top:3px solid #f0883e;padding-top:18px;">💡 윈터의 이번 주 상품 추천</h2>
  • 부제: <p style="color:#8b949e;font-size:0.9rem;">은행연합회 공시 데이터 기반 팩트 큐레이션 | 출처: 전국은행연합회 공시, {kfb["scraped_at"]} 기준</p>
  • 2×2 그리드: <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;">
    모바일 대응: style 속성에 직접 작성하되 @media는 생략 (모바일은 단순 세로 배열도 OK)
  • 카드 4개 각각 <div style="background:#1a1f2e;border:1px solid #f0883e44;border-radius:12px;padding:20px;">:
    카드①: 🏧 단기/파킹 — 6개월 금리 높은 상품 1~2개 추천, 블로그 말투 2~3줄
    카드②: 🏆 최고금리 예금 TOP3 — 12개월 최고우대금리 상위 3개, 기본→최고 금리 표기, 우대조건 주의
    카드③: 📈 목돈 장기 굴리기 — 24개월 높은 상품 2개, 1000만원×2년 세전이자 계산 포함
    카드④: 🌱 첫 적금 추천 — 12개월 금리 높은 적금 2개, 월10만원×12개월 예상 수령액 계산
  • 금리: <span style="color:#3fb950;font-weight:700;">연 X.XX%</span>
  • 강조: <span style="color:#f0883e;font-weight:600;">키워드</span>
  • 각 카드 하단: <small style="color:#8b949e;">(출처: 전국은행연합회 공시, {kfb["scraped_at"]} 기준)</small>"""

    resp = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4000,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = resp.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1]
        if "```" in raw:
            raw = raw.rsplit("```", 1)[0]
    try:
        return __import__("json").loads(raw)
    except Exception:
        # JSON 파싱 실패 시 그냥 curation에 원본 삽입
        return {"intro": "", "news_analysis": "", "curation": raw}


# ──────────────────────────────────────────────
# 4. HTML 보고서 생성 (하이브리드: Python 템플릿 + Claude 편집)
# ──────────────────────────────────────────────
def generate_html(kfb: dict, kakao: dict, news: dict, report_date: str, week_str: str) -> str:
    kfb_cnt   = len(kfb["deposits"]) + len(kfb["savings"])
    kakao_cnt = len(kakao["products"])

    # ── Step 1: Python이 테이블·구조 빌드
    dep_table   = _build_deposit_table(kfb["deposits"])
    sav_table   = _build_savings_table(kfb["savings"])
    news_cards  = _build_news_section(news)
    refs_html   = _build_refs_section(news)

    # ── Step 2: Claude가 서론·뉴스분석·큐레이션만 생성
    editorial = _claude_editorial(kfb, kakao, news, report_date, week_str)

    intro_html       = editorial.get("intro", "<p>이번 주 금리 현황을 확인하세요.</p>")
    news_analysis    = editorial.get("news_analysis", "")
    curation_html    = editorial.get("curation", "")

    # ── Step 3: 카카오뱅크 섹션
    kakao_html = ""
    for p in kakao["products"]:
        rates_txt = " | ".join(p["rates"][:6]) if p["rates"] else (p["rate_table"][:300] if p["rate_table"] else "금리 정보 없음")
        kakao_html += (
            f'<div style="background:#161b22;border:1px solid #30363d;border-radius:8px;padding:14px 16px;margin-bottom:12px;">'
            f'<strong style="color:#3fb950;">{p["name"]}</strong><br>'
            f'<span style="font-size:0.85rem;color:#c9d1d9;">{rates_txt}</span><br>'
            f'<a href="{p["url"]}" style="display:inline-block;background:#21262d;color:#58a6ff;font-size:0.78rem;padding:4px 10px;border-radius:6px;text-decoration:none;margin-top:8px;" target="_blank">[공식 홈페이지 바로가기]</a>'
            f'</div>\n'
        )

    # ── Step 4: 전체 HTML 조립
    html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>예금·적금 비교 보고서 — {report_date}</title>
<style>
body{{font-family:'Noto Sans KR',Arial,sans-serif;background:#0d1117;color:#c9d1d9;margin:0;padding:0;}}
.wrap{{max-width:900px;margin:0 auto;padding:24px 16px;}}
h1{{color:#c9d1d9;font-size:1.5rem;line-height:1.4;margin-bottom:6px;}}
h2{{color:#58a6ff;font-size:1.1rem;margin:32px 0 12px;}}
p{{line-height:1.8;margin-bottom:12px;}}
.banner{{background:#1a2744;border:1px solid #58a6ff44;border-radius:10px;padding:14px 18px;margin-bottom:24px;font-size:0.85rem;color:#8b949e;}}
.banner strong{{color:#58a6ff;}}
.sec{{background:#161b22;border:1px solid #30363d;border-radius:10px;padding:20px 22px;margin-bottom:24px;}}
.sec.blue{{border-top:3px solid #58a6ff;}}
.sec.yellow{{border-top:3px solid #e3b341;}}
.sec.green{{border-top:3px solid #3fb950;}}
.sec.orange{{border-top:3px solid #f0883e;}}
.sec h2{{margin-top:0;}}
.tbl-wrap{{overflow-x:auto;margin-top:12px;}}
.src-note{{font-size:0.78rem;color:#8b949e;margin-top:10px;display:block;}}
a.btn{{display:inline-block;background:#21262d;color:#58a6ff;font-size:0.78rem;padding:5px 12px;border-radius:6px;text-decoration:none;margin-top:10px;border:1px solid #30363d;}}
a.btn:hover{{background:#30363d;}}
.author{{font-size:0.85rem;color:#8b949e;margin-bottom:24px;}}
</style>
</head>
<body>
<div class="wrap">

  <!-- 배너 -->
  <div class="banner">
    📊 <strong>은행연합회 공시 {kfb_cnt}개 상품</strong> |
    <strong>카카오뱅크 {kakao_cnt}개</strong> |
    뉴스 {news['total_valid']}건 | 링크 검증 완료<br>
    <span>수집 시각: {kfb['scraped_at']} (전국은행연합회) / {kakao['scraped_at']} (카카오뱅크)</span>
  </div>

  <!-- 헤더 -->
  <h1>🏦 이번 주 예금·적금 금리 완전 비교<br>
  <small style="font-size:0.65em;color:#8b949e;">{week_str} · 은행연합회 공시 {kfb_cnt}개 상품 기준</small></h1>
  <div class="author">✍️ <strong>비서 윈터</strong> · {report_date} 작성</div>

  <!-- 서론 -->
  <div class="sec">
    <h2>📌 이번 주 금리 시장 동향</h2>
    {intro_html}
  </div>

  <!-- 신규/특판 상품 소식 -->
  <div class="sec yellow">
    <h2>⭐ 이번 주 신규·특판 상품 소식</h2>
    {news_cards}
  </div>

  <!-- 은행연합회 비교표 -->
  <div class="sec blue">
    <h2>🏛️ 전국은행연합회 공식 금리공시 비교표</h2>
    <p style="font-size:0.85rem;color:#8b949e;">공시 기준일: {kfb['scraped_at']} · 19개 시중은행 전체 · 단리 기준</p>

    <strong style="color:#c9d1d9;">📋 정기예금 ({len(kfb['deposits'])}개 상품 — 12개월 기준금리 높은 순)</strong>
    <div class="tbl-wrap">{dep_table}</div>
    <span class="src-note">※ 최고금리는 우대조건 충족 시 적용. (출처: 전국은행연합회 소비자포털, {kfb['scraped_at']} 공시 기준)</span>

    <br><br>
    <strong style="color:#c9d1d9;">📋 정액적립식 적금 ({len(kfb['savings'])}개 상품 — 12개월 기준금리 높은 순)</strong>
    <div class="tbl-wrap">{sav_table}</div>
    <span class="src-note">※ 최고금리는 우대조건 충족 시 적용. (출처: 전국은행연합회 소비자포털, {kfb['scraped_at']} 공시 기준)</span>

    <br>
    <a href="https://portal.kfb.or.kr/compare/receiving_deposit_3.php" class="btn" target="_blank">[은행연합회 전체 공시 확인]</a>
  </div>

  <!-- 카카오뱅크 -->
  <div class="sec green">
    <h2>🐱 카카오뱅크 실시간 금리</h2>
    <p style="font-size:0.85rem;color:#8b949e;">수집 시각: {kakao['scraped_at']} · 공식 홈페이지 기준</p>
    {kakao_html}
  </div>

  <!-- 시중은행 동향 -->
  <div class="sec">
    <h2>📰 이번 주 시중은행 동향</h2>
    {news_analysis}
  </div>

  <!-- 주제별 추천 큐레이션 -->
  <div class="sec orange">
    {curation_html}
  </div>

  <!-- 하단 출처 -->
  <div class="sec" style="margin-top:32px;">
    <h2>📎 참고 출처 · 공식 링크</h2>
    <div style="line-height:2.2;">
    {refs_html}
    </div>
  </div>

  <p style="text-align:center;color:#8b949e;font-size:0.78rem;margin-top:32px;">
    ⚠️ 본 보고서는 참고용이며 실제 가입 전 각 금융기관 공식 홈페이지에서 최신 금리를 확인하세요.<br>
    자동 생성: 비서 윈터 (GitHub Actions) · {report_date}
  </p>

</div>
</body>
</html>"""

    return html


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
def send_telegram(report_url: str, report_date: str, kfb: dict, kakao: dict, news: dict):
    token   = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        return

    # 은행연합회 상위 3개 예금 요약 (12개월 기준금리 기준)
    top_deps = sorted(
        [d for d in kfb["deposits"] if d["rate_12m"] not in ("-", "")],
        key=lambda x: float(x["rate_12m"]) if x["rate_12m"].replace(".","").isdigit() else 0,
        reverse=True,
    )[:3]
    kfb_summary = ""
    for d in top_deps:
        kfb_summary += f"• {d['bank']} {d['product']}: 기본 {d['rate_12m']}% / 최고 {d['max_12m']}%\n"
    if not kfb_summary:
        kfb_summary = "  (수집 데이터 없음)\n"

    # 카카오뱅크 대표 금리
    kakao_summary = ""
    for p in kakao["products"]:
        if p["rates"]:
            kakao_summary += f"• {p['name']}: {p['rates'][0]}\n"

    msg = (
        f"🏦 *예금·적금 상품 비교 보고서*\n"
        f"📅 {report_date}\n\n"
        f"🏛️ *은행연합회 공시 TOP3 (12개월 기준금리)*\n"
        f"{kfb_summary}"
        f"_(출처: 전국은행연합회, {kfb['scraped_at']} 기준)_\n\n"
        f"🐱 *카카오뱅크 실시간 금리*\n"
        f"{kakao_summary}"
        f"📰 뉴스 기사 {news['total_valid']}건 | 신규 상품 {len(news['new_products'])}건\n\n"
        f"🔍 *공식 확인*\n"
        f"• [은행연합회 금리공시](https://portal.kfb.or.kr/compare/receiving_deposit_3.php)\n"
        f"• [금융감독원 금융상품한눈에](https://finlife.fss.or.kr/Main.do)\n\n"
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
    print(f"  은행연합회 공시 + 카카오뱅크 + 뉴스 기사")
    print("=" * 55)

    print("\n[1/6] 은행연합회 공식 금리공시 수집 중...")
    kfb = scrape_kfb()
    print(f"  → 정기예금 {len(kfb['deposits'])}개 / 적금 {len(kfb['savings'])}개 수집 완료")

    print("\n[2/6] 카카오뱅크 공식 사이트 스크래핑...")
    kakao = scrape_kakaobank()
    print(f"  → {len(kakao['products'])}개 상품 수집 완료")

    print("\n[3/6] 뉴스 수집 및 링크 검증 중...")
    news = get_finance_news()
    print(f"  → 유효 기사 {news['total_valid']}건 (신규:{len(news['new_products'])} / 일반:{len(news['general_finance'])})")

    print("\n[4/6] Claude AI 분석 및 HTML 생성 중...")
    html_content = generate_html(kfb, kakao, news, report_date, week_str)
    print("  → HTML 생성 완료")

    docs_dir    = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs")
    os.makedirs(docs_dir, exist_ok=True)
    output_path = f"{docs_dir}/finance_{file_date}.html"
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html_content)
    print(f"  → {output_path} 저장 완료")

    print("\n[5/6] 인덱스 업데이트...")
    update_index()

    report_url = f"https://jinhae8971.github.io/gcp/finance_{file_date}.html"
    print(f"\n[6/6] 텔레그램 전송...")
    send_telegram(report_url, report_date, kfb, kakao, news)

    print(f"\n✅ 완료!")
    print(f"   은행연합회 공시: 예금 {len(kfb['deposits'])}개 / 적금 {len(kfb['savings'])}개")
    print(f"   카카오뱅크: {len(kakao['products'])}개 상품")
    print(f"   뉴스 기사: {news['total_valid']}건")
    print(f"   보고서: {report_url}")


if __name__ == "__main__":
    main()
