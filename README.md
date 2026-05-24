# gcp — 매크로 리서치 대시보드 모음

GitHub Pages 로 자동 배포되는 정적 대시보드 + 일별 데이터 갱신 워크플로우들을 모아둔 레포.

## 주요 페이지

- **`docs/global_money_flow.html`** — 글로벌 자금흐름 매크로 터미널. 통화·DXY (Frankfurter), M2 (FRED), VIX (Alpha Vantage), ETF 흐름·리더보드·자산회전·국가-자산 버블 (Claude Opus 4.7 + web_search).
  - 라이브: https://jinhae8971.github.io/gcp/global_money_flow.html
  - 생성기: `generate_global_flow_data.py` → `.github/workflows/global_flow_data.yml` (매일 22:00 UTC)
- **`docs/Dashboard.html`** — 코스피 주도섹터·수급 대시보드 (`generate_dashboard_data.py`)
- **`docs/dashboard.html`** — 윈터 자동화 대시보드 (리포트 인덱스)
- **`docs/index.html`** — 메인 인덱스
- **`docs/전략테스터.html`** — KOSPI 백테스트 시스템 (DCA/VA·RSI/MACD 매도 빌더·벤치마크 비교·리스크 지표). 단일 자족형 페이지 (React + Babel CDN).
  - 라이브: https://jinhae8971.github.io/gcp/전략테스터.html
  - 데이터: `generate_strategy_tester_data.py` → `docs/strategy_tester_data.json` (KOSPI/KOSPI200/KOSDAQ 일봉, Naver siseJson + pykrx 폴백). JSON 이 없으면 페이지가 모의 데이터로 자동 폴백.
  - 워크플로: `.github/workflows/strategy_tester_data.yml` (평일 17:00 KST)

## 로컬 개발 (Docker)

두 대시보드 (KOSPI Intel + Global Money MOVE) 모두 **하나의 `docker compose` 스택**으로 띄웁니다. KOSPI 데이터는 컨테이너에서 5분마다 자동 갱신되고, Global Money MOVE 의 AI 번들은 명령으로 1회성 생성합니다.

```bash
# 1) (선택) API 키 준비
cp .env.example .env
# .env 를 열어 ANTHROPIC_API_KEY / KRX_ID / KRX_PW 입력 — 모두 선택사항
#   ANTHROPIC_API_KEY: AI 번들 갱신 시 필요 (make refresh)
#   KRX_ID/PW:        KOSPI Intel 의 풀데이터 사용 시 필요 (없으면 Naver 폴백)

# 2) 두 대시보드 띄우기
make up
# → http://localhost:8080/                       (메인 인덱스)
# → http://localhost:8080/Dashboard.html         (KOSPI Intel — data 컨테이너가 5분마다 갱신)
# → http://localhost:8080/global_money_flow.html (Global Money MOVE)

# 3) Global Money MOVE AI 번들 1회 갱신 (선택)
make refresh
# → Claude Opus 4.7 호출 → docs/global_flow_data.json → 브라우저 새로고침

# 4) KOSPI 데이터 즉시 재생성
make refresh-kospi

# 5) 정리
make down
```

`make` 만 치면 사용 가능한 명령 목록이 나옵니다.

| 명령 | 설명 |
|---|---|
| `make up` | data + web 컨테이너 띄우기 (기본 :8080) |
| `make down` | 컨테이너 정리 (볼륨 유지) |
| `make restart` | web + data 재시작 |
| `make logs` | nginx 로그 |
| `make logs-data` | KOSPI 데이터 5분 cron 로그 |
| `make refresh` | Global Money MOVE AI 번들 1회 갱신 (Anthropic API) |
| `make refresh-kospi` | KOSPI 데이터 즉시 재생성 |
| `make shell-web` / `shell-data` / `shell-gen` | 각 컨테이너 셸 |
| `make clean` | 모든 컨테이너 + 이미지 + 볼륨 제거 |

`docker compose` 만으로도 동일하게 동작합니다 (Make 의존성 없음). Global Money MOVE 생성기는 `--profile gmm` 으로만 켜집니다:
```bash
docker compose --profile gmm run --rm gmm-generator
```

### 포트 변경

```bash
GMM_WEB_PORT=9000 make up
# 또는 .env 에 GMM_WEB_PORT=9000 추가
```

## 데이터 소스 요약

| 영역 | 출처 | 키 필요? | 갱신 |
|---|---|---|---|
| 통화 8종, DXY 계산 | Frankfurter (ECB) | ❌ | 페이지 로드 시 |
| M2 5개국 YoY | FRED | ✅ 사용자 입력 (브라우저 localStorage) | 페이지 로드 시 |
| VIX | Alpha Vantage | ✅ 사용자 입력 (localStorage) | 페이지 로드 시 |
| ETF 흐름 / 리더보드 / 자산회전 / 국가×자산 버블 / geoFlows / 매크로 narrative | Claude Opus 4.7 + web_search → ETF.com / IIF / BIS / Bloomberg / Reuters / Yahoo Finance | ✅ `ANTHROPIC_API_KEY` GitHub Secret | 매일 22:00 UTC |
| 상단 KPI (글로벌 자금이동·미국→아시아·채권→위험자산 회전·M2 가중평균) | 위 데이터에서 클라이언트가 derive | — | AI 번들 + FRED 도착 시 |
| Hero Sankey / Chord | 큐레이션 샘플 (자산 클래스 회전 매트릭스 무료 실시간 소스 없음) | — | — |

키가 없거나 워크플로우가 아직 한 번도 안 돌았으면 자연스럽게 큐레이션 샘플로 폴백합니다.

## CI / 자동화

- `.github/workflows/global_flow_data.yml` — 매일 22:00 UTC (07:00 KST) Claude API 호출 → JSON 커밋
- `.github/workflows/weekly_finance.yml` — 주간 예적금/금융 보고서
- `.github/workflows/weekly_kosdaq.yml` — 주간 코스닥 분석
- `.github/workflows/weekly_report.yml` — 평일 일일 코스피 리포트
- `.github/workflows/strategy_tester_data.yml` — 전략테스터 백테스트 실데이터 (평일 17:00 KST → `docs/strategy_tester_data.json`)

새 워크플로우 첫 실행 시 GitHub Secret 으로 `ANTHROPIC_API_KEY` (그리고 다른 워크플로우용 `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`) 가 등록되어 있어야 합니다.
