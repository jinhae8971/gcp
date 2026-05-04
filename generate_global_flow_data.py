"""
Generates docs/global_flow_data.json for the Global Money MOVE dashboard.

Calls Claude Opus 4.7 with the web_search_20260209 + web_fetch_20260209
server tools to ground every numeric claim in published sources from the
last ~14 days:
  - ETF flows by category (ETF.com / ICI / Bloomberg / Reuters)
  - Top inflow / outflow leaderboard (last 7 days)
  - Cross-border capital flow estimates (IIF / BIS / IMF)
  - One-line Korean narratives per dashboard panel

Run via .github/workflows/global_flow_data.yml on a schedule.
Reads ANTHROPIC_API_KEY from the environment.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import anthropic

REPO_ROOT = Path(__file__).resolve().parent
OUT_PATH = REPO_ROOT / "docs" / "global_flow_data.json"
MODEL = "claude-opus-4-7"
MAX_PAUSE_RESUMES = 4

ETF_CATEGORIES = """1. 주식 — 신흥아시아   (EM Asia Eq,    color: cyan)
2. 주식 — 미국 대형    (US Large Cap,  color: cyan)
3. 주식 — 미국 소형    (US Small Cap,  color: cyan)
4. 주식 — 일본         (Japan Eq,      color: cyan)
5. 채권 — 단기         (ST Bonds,      color: purple)
6. 채권 — 장기         (LT Bonds,      color: purple)
7. 채권 — 회사채       (Corp Bonds,    color: purple)
8. 금 / 귀금속         (Gold/PM,       color: amber)
9. 원자재 — 에너지     (Energy Cmdty,  color: lime)
10. 원자재 — 산업금속  (Ind. Metals,   color: lime)
11. 머니마켓           (Money Market,  color: mag)"""

SCHEMA = """{
  "asOf": "<ISO 8601 UTC timestamp of when the underlying data was published>",
  "etfFlows": [
    {
      "cat":   "<Korean category label, exactly matching the list below>",
      "en":    "<English label, ≤24 chars, exactly matching the list below>",
      "value": <signed $B, last 7 days>,
      "aum":   <total AUM in $B for the category>,
      "source":"<short source name + URL>"
    }
    // 8-11 entries; omit categories with no recent published data, do NOT pad with zeros
  ],
  "leaderboard": {
    "inflows": [
      {
        "name":   "<Korean fund/category name, ≤16 chars>",
        "en":     "<English name, ≤32 chars>",
        "ticker": "<3-5 char ticker or symbol>",
        "value":  <POSITIVE $B, last 7 days>,
        "pct":    <% of AUM>,
        "source": "<short source + URL>"
      }
      // exactly 6 entries, ranked highest inflow first
    ],
    "outflows": [
      // exactly 6 entries, ranked largest outflow first; "value" must be NEGATIVE $B
    ]
  },
  "geoFlows": [
    {
      "from":  "<one of: US|EU|CN|JP|IN|KR|SEA|ME|CH|UK|CA|AU|BR>",
      "to":    "<same set>",
      "value": <signed $B, last 30 days>,
      "asset": "<one of: equities|bonds|gold|commodities|cash>",
      "source":"<short source + URL>"
    }
    // 8-15 entries based on the most recent IIF Capital Flows Tracker / BIS quarterly / IMF prints
  ],
  "assetRotation": [
    {
      "id":    "<one of: equities|bonds|gold|commodities|cash>",
      "kr":    "<Korean label: 주식|채권|금|원자재|현금성자산>",
      "en":    "<English: Equities|Bonds|Gold|Commodities|Cash & MM>",
      "flow":  <signed $B, last 30 days NET into this asset class — sum across all relevant ETF categories>,
      "prev":  <signed $B, prior 30-day window for comparison>,
      "share": <% of total absolute flow across all 5 classes, integer 0-100>,
      "color": "<one of: cyan|purple|amber|lime|mag — per dashboard convention: equities=cyan, bonds=purple, gold=amber, commodities=lime, cash=mag>",
      "source":"<short source + URL>"
    }
    // EXACTLY 5 entries — one per asset class. Aggregate from etfFlows + ICI weekly fund flows.
  ],
  "bubble": [
    {
      "id":    "<short stable id, e.g. us_eq, in_eq, jp_eq, gold, copper>",
      "kr":    "<Korean label, e.g. 미국주식, 인도주식>",
      "ret":   <YTD return %, signed>,
      "flow":  <30-day net flow $B, signed>,
      "aum":   <AUM in $B>,
      "color": "<cyan|purple|amber|lime|mag — same convention as assetRotation>",
      "source":"<short source + URL — Yahoo Finance / ETF.com>"
    }
    // 10-13 representative ETFs spanning: US/EU/JP/CN/IN/SEA/KR equities, US/EM bonds, gold, oil, copper, money market
  ],
  "narratives": {
    "hero":          "<one-line Korean macro narrative, ≤100 chars>",
    "assetRotation": "<one-line Korean for asset-rotation panel, ≤80 chars, end with ↗ ↘ or →>",
    "m2":            "<one-line Korean for M2 panel, ≤80 chars>",
    "currency":      "<one-line Korean for currency panel, ≤80 chars>",
    "leaderboard":   "<one-line Korean for leaderboard panel, ≤80 chars>",
    "etf":           "<one-line Korean for ETF panel, ≤80 chars>"
  }
}"""

SYSTEM_PROMPT = f"""You are a macro-research data engineer producing a JSON snapshot for a Korean institutional macro dashboard (Global Money MOVE).

# Grounding rules — non-negotiable
- Use the web_search tool to ground EVERY numeric claim in published sources from the LAST 14 DAYS. Use web_fetch when you need to read a specific page in detail.
- Preferred sources by topic:
  - ETF flows / leaderboard: ETF.com flows tool, etf.morningstar.com, ICI weekly statistics, Bloomberg, Reuters, Lipper.
  - Cross-border / EM capital flows: IIF Capital Flows Tracker, BIS Quarterly Review, IMF press releases.
  - Macro narrative context: Reuters, Bloomberg, FT, Nikkei, WSJ, Yonhap.
- NEVER invent numbers. If a category has no published recent data, omit it from the array. Do not pad with zeros or guesses.
- Each numeric entry MUST include a "source" field with a short source name + a real, fetchable URL.
- Cross-reference at least 2 sources for the headline leaderboard items.

# Output format
Return ONLY a single valid JSON object matching this schema (no markdown fence, no prose):

{SCHEMA}

# ETF category whitelist (use the exact Korean and English labels)
{ETF_CATEGORIES}

# Geo / asset code whitelist
- Geo node codes are exactly: US, EU, CN, JP, IN, KR, SEA, ME, CH, UK, CA, AU, BR.
- Asset codes are exactly: equities, bonds, gold, commodities, cash.

# Style
- All Korean labels and narratives in 한국어, macro-research register (concise, factual).
- Narratives reflect the actual numbers you found, not generic phrasing.
- End directional narratives with ↗ ↘ or → where natural."""

USER_PROMPT_TEMPLATE = """Today is {today_iso} UTC. Build the global_flow_data.json snapshot per the schema in your system prompt.

Workflow:
1. web_search this week's ETF flow leaderboard (ETF.com / ICI / Reuters).
2. web_search the last 30 days of cross-border capital flow figures (IIF Capital Flows Tracker / BIS / IMF).
3. web_search YTD returns + 30D net flows + AUM for ~12 representative ETFs spanning US/EU/JP/CN/IN/SEA/KR equities, US/EM bonds, gold, oil, copper, money market (Yahoo Finance, ETF.com).
4. Aggregate the etfFlows you collected by asset class to derive the 5-row assetRotation table. Use sign convention: positive = net into that class.
5. Cross-reference at least 2 sources for headline leaderboard items.
6. Compose Korean narratives that reflect the figures you found.
7. Assemble the JSON. Mentally validate it parses before returning.

Return ONLY the JSON object."""


def main() -> int:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY environment variable is required", file=sys.stderr)
        return 1

    client = anthropic.Anthropic(api_key=api_key)
    today_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    messages: list[dict] = [{
        "role": "user",
        "content": USER_PROMPT_TEMPLATE.format(today_iso=today_iso),
    }]

    tools = [
        {"type": "web_search_20260209", "name": "web_search"},
        {"type": "web_fetch_20260209", "name": "web_fetch"},
    ]

    final_message = None
    iterations = 0
    while iterations <= MAX_PAUSE_RESUMES:
        iterations += 1
        with client.messages.stream(
            model=MODEL,
            max_tokens=32000,
            system=SYSTEM_PROMPT,
            thinking={"type": "adaptive"},
            output_config={"effort": "high"},
            tools=tools,
            messages=messages,
        ) as stream:
            final_message = stream.get_final_message()

        usage = final_message.usage
        print(
            f"iter={iterations} stop={final_message.stop_reason} "
            f"in={usage.input_tokens} out={usage.output_tokens} "
            f"cache_read={getattr(usage, 'cache_read_input_tokens', 0)} "
            f"cache_create={getattr(usage, 'cache_creation_input_tokens', 0)}",
            file=sys.stderr,
        )

        if final_message.stop_reason == "pause_turn":
            messages.append({"role": "assistant", "content": final_message.content})
            continue
        break

    if final_message is None:
        print("ERROR: no response", file=sys.stderr)
        return 2

    if final_message.stop_reason == "refusal":
        print("ERROR: Claude refused the request", file=sys.stderr)
        return 3

    if final_message.stop_reason == "pause_turn":
        print(f"ERROR: still paused after {MAX_PAUSE_RESUMES} resumes — increase budget", file=sys.stderr)
        return 4

    text_blocks = [b.text for b in final_message.content if getattr(b, "type", None) == "text"]
    full_text = "\n".join(text_blocks).strip()
    if not full_text:
        print("ERROR: empty text response", file=sys.stderr)
        return 5

    # Strip an optional ```json ... ``` fence
    if full_text.startswith("```"):
        lines = full_text.split("\n")
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        full_text = "\n".join(lines)

    start = full_text.find("{")
    end = full_text.rfind("}")
    if start < 0 or end < 0:
        print("ERROR: no JSON object found in response", file=sys.stderr)
        print(f"--- response ---\n{full_text[:1500]}\n----------------", file=sys.stderr)
        return 6

    json_str = full_text[start : end + 1]

    try:
        data = json.loads(json_str)
    except json.JSONDecodeError as e:
        print(f"ERROR: invalid JSON: {e}", file=sys.stderr)
        print(f"--- json ---\n{json_str[:2000]}\n------------", file=sys.stderr)
        return 7

    if not isinstance(data, dict):
        print("ERROR: top-level must be a JSON object", file=sys.stderr)
        return 8

    # Validate the parts the dashboard depends on
    leaderboard = data.get("leaderboard")
    if not isinstance(leaderboard, dict):
        print("ERROR: leaderboard missing", file=sys.stderr)
        return 9
    inflows  = leaderboard.get("inflows")  or []
    outflows = leaderboard.get("outflows") or []
    if not isinstance(inflows, list) or not isinstance(outflows, list):
        print("ERROR: leaderboard.inflows/outflows must be arrays", file=sys.stderr)
        return 9
    if len(inflows) < 3 or len(outflows) < 3:
        print(f"ERROR: leaderboard too thin (in={len(inflows)} out={len(outflows)}; need ≥3 each)", file=sys.stderr)
        return 9
    for row in inflows + outflows:
        if not isinstance(row, dict) or "value" not in row or "name" not in row:
            print(f"ERROR: malformed leaderboard row: {row}", file=sys.stderr)
            return 9

    etf_flows = data.get("etfFlows") or []
    if not isinstance(etf_flows, list) or len(etf_flows) < 3:
        print(f"ERROR: etfFlows too thin (n={len(etf_flows) if isinstance(etf_flows, list) else 'invalid'}; need ≥3)", file=sys.stderr)
        return 10
    valid_colors = {"cyan", "purple", "amber", "lime", "mag"}
    for row in etf_flows:
        if not isinstance(row, dict) or row.get("color") not in valid_colors:
            print(f"ERROR: malformed etf row (bad color): {row}", file=sys.stderr)
            return 10

    # geoFlows is optional but if present must be well-formed
    valid_assets = {"equities", "bonds", "gold", "commodities", "cash"}
    valid_nodes = {"US","EU","CN","JP","IN","KR","SEA","ME","CH","UK","CA","AU","BR"}
    geo_flows = data.get("geoFlows") or []
    if isinstance(geo_flows, list):
        cleaned = []
        for row in geo_flows:
            if (isinstance(row, dict)
                and row.get("from") in valid_nodes
                and row.get("to") in valid_nodes
                and row.get("asset") in valid_assets):
                cleaned.append(row)
            else:
                print(f"WARN: dropping invalid geoFlow: {row}", file=sys.stderr)
        data["geoFlows"] = cleaned

    # assetRotation: drop malformed rows; warn if fewer than 4 of the 5 classes
    valid_class_ids = {"equities", "bonds", "gold", "commodities", "cash"}
    asset_rotation = data.get("assetRotation") or []
    if isinstance(asset_rotation, list):
        cleaned = []
        for row in asset_rotation:
            if (isinstance(row, dict)
                and row.get("id") in valid_class_ids
                and row.get("color") in valid_colors
                and isinstance(row.get("flow"), (int, float))):
                cleaned.append(row)
            else:
                print(f"WARN: dropping invalid assetRotation row: {row}", file=sys.stderr)
        if len(cleaned) < 4:
            print(f"WARN: assetRotation has only {len(cleaned)}/5 classes — panel will fall back to sample", file=sys.stderr)
        data["assetRotation"] = cleaned

    # bubble: drop malformed rows; warn if fewer than 6 entries
    bubble = data.get("bubble") or []
    if isinstance(bubble, list):
        cleaned = []
        for row in bubble:
            if (isinstance(row, dict)
                and row.get("color") in valid_colors
                and isinstance(row.get("ret"), (int, float))
                and isinstance(row.get("flow"), (int, float))
                and isinstance(row.get("aum"), (int, float))
                and row.get("kr") and row.get("id")):
                cleaned.append(row)
            else:
                print(f"WARN: dropping invalid bubble row: {row}", file=sys.stderr)
        if len(cleaned) < 6:
            print(f"WARN: bubble has only {len(cleaned)} rows — chart will fall back to sample", file=sys.stderr)
        data["bubble"] = cleaned

    # Stamp metadata for the dashboard's status badges
    data["_generatedAt"] = datetime.now(timezone.utc).isoformat()
    data["_model"] = MODEL
    data["_usage"] = {
        "input_tokens": final_message.usage.input_tokens,
        "output_tokens": final_message.usage.output_tokens,
        "cache_read_input_tokens": getattr(final_message.usage, "cache_read_input_tokens", 0),
    }

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {OUT_PATH} ({OUT_PATH.stat().st_size} bytes)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
