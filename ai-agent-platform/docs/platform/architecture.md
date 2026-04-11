# System Architecture

## Overview

사내 내재화 에이전틱 코딩 플랫폼. 다양한 LLM 프로바이더와 하네스 패턴을 통합 관리하고,
정량적 평가 프레임워크를 통해 최적의 조합을 찾아내는 시스템.

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                        Web Dashboard / CLI                       │
├─────────────────────────────────────────────────────────────────┤
│                   FastAPI Server (REST + WebSocket)               │
│                 POST /sessions  GET /models  POST /eval          │
├──────────┬──────────┬───────────┬──────────┬────────────────────┤
│          │          │           │          │                      │
│  Agent   │  Model   │   Tool    │  Eval    │   Prompt             │
│  Core    │  Gateway │  Registry │  Runner  │   Registry           │
│          │          │           │          │                      │
│ ┌──────┐ │ ┌──────┐ │ ┌───────┐ │ ┌──────┐ │ ┌────────┐         │
│ │Loop  │ │ │Route │ │ │Builtin│ │ │Score │ │ │Version │         │
│ │Orch. │ │ │Fallbk│ │ │MCP   │ │ │Report│ │ │Render  │         │
│ │Sessn │ │ │CircBk│ │ │Custom │ │ │Gate  │ │ │A/B     │         │
│ └──────┘ │ └──────┘ │ └───────┘ │ └──────┘ │ └────────┘         │
├──────────┴──────────┴───────────┴──────────┴────────────────────┤
│                       Provider Adapters                          │
│         ┌──────────┐  ┌────────┐  ┌────────┐                    │
│         │Anthropic │  │OpenAI  │  │Google  │  + extensible       │
│         │Claude 4  │  │GPT-4o  │  │Gemini  │                    │
│         └──────────┘  └────────┘  └────────┘                    │
├─────────────────────────────────────────────────────────────────┤
│                     Observability Layer                           │
│           OpenTelemetry Tracing  ·  structlog  ·  Metrics        │
├─────────────────────────────────────────────────────────────────┤
│                     Infrastructure                               │
│        Docker Compose  ·  Redis  ·  GitHub Actions CI/CD         │
└─────────────────────────────────────────────────────────────────┘
```

## Core Components

### 1. Agent Core (`core/`)
- **Agent Loop**: 메시지 → LLM 호출 → 도구 실행 → 결과 피드백의 반복
- **Orchestrator**: 멀티 에이전트 패턴 (Supervisor, Parallel, Pipeline)
- **Session**: 대화 상태, 토큰 사용량, 비용 추적

### 2. Model Gateway (`models/`)
- **Provider Abstraction**: 각 LLM 벤더를 통합 인터페이스로 정규화
- **Circuit Breaker**: 장애 감지 → 자동 차단 → 복구 후 재시도
- **Fallback Chain**: Primary 모델 실패 시 자동으로 대체 모델 사용
- **Model Registry**: 가격, 성능, 용도별 모델 카탈로그

### 3. Tool Registry (`tools/`)
- **Built-in Tools**: 파일 I/O, 셸 실행, 검색 (샌드박스 내)
- **MCP Integration**: Model Context Protocol 기반 외부 도구 연결
- **Parallel Classification**: 병렬 실행 가능 여부 자동 분류
- **Safety**: 경로 탈출 방지, 타임아웃, 출력 크기 제한

### 4. Harness System (`harness/`)
- **BaseHarness**: 교체 가능한 에이전트 행동 패턴
- **ReAct**: 추론-행동-관찰 반복 (기본값)
- **Plan-Execute**: 계획 수립 후 단계별 실행
- 새 하네스 추가: `BaseHarness`를 상속하고 `prepare_request()`/`should_stop()` 구현

### 5. Eval Framework (`eval/`)
- **EvalRunner**: 모델 × 하네스 조합을 벤치마크 데이터셋으로 평가
- **Scorers**: exact_match, contains, regex, test_pass, code_quality, LLM-as-Judge, Pairwise 비교
- **CI Gate**: 평균 점수가 임계값 미달 시 PR 머지 차단
- **Report**: JSON + 인터랙티브 HTML 대시보드 (비교 차트, 트렌드 스파크라인)
- **History**: 파일 기반 결과 히스토리, 회귀 감지 (5% 이상 하락 경고)
- **A/B Testing**: Welch's t-test 기반 프롬프트/하네스 비교 (95% 신뢰구간)
- **Eval Worker**: Redis 큐 기반 비동기 평가 작업 처리

### 6. Prompt Registry (`prompts/`)
- **Versioning**: 프롬프트를 불변 버전으로 관리
- **Template Rendering**: `{{variable}}` 치환
- **Hot-swap**: 재배포 없이 프롬프트 변경 가능

## Data Flow

```
User Message
    ↓
API Server (FastAPI)
    ↓
Session Manager (create/load session)
    ↓
Harness.prepare_request() → LLMRequest
    ↓
Model Gateway
    ├─ Route to provider (Anthropic/OpenAI/Google)
    ├─ Circuit breaker check
    ├─ Retry with exponential backoff
    └─ Fallback to alternative provider
    ↓
ChatResponse (text + tool_calls)
    ↓
Tool Registry.execute()
    ├─ Parallel-safe tools → asyncio.gather()
    └─ Sequential tools → one by one
    ↓
Results fed back to session messages
    ↓
Harness.should_stop() → continue or finish
    ↓
Response to user (REST or WebSocket stream)
```

## Security Model

| Layer | Mechanism |
|-------|-----------|
| File I/O | 작업 공간 밖 경로 접근 차단 (`_validate_path`) |
| Shell | 타임아웃 + 출력 크기 제한 |
| API | Secret key 인증 + CORS |
| Container | Non-root 사용자 실행 + isolated workspace volume |
| Network | 프로바이더 API 키 환경변수 분리 |
