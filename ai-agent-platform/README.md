# Agent Platform

사내 내재화 에이전틱 코딩 시스템 - 멀티 모델 평가 및 오케스트레이션 플랫폼

## Features

- **Multi-Model Gateway**: Anthropic, OpenAI, Google 통합 + Circuit Breaker + 자동 Fallback
- **Pluggable Harness**: ReAct, Plan-Execute 등 교체 가능한 에이전트 행동 패턴
- **Eval Framework**: 모델 x 하네스 조합 벤치마크 + CI 품질 게이트
- **Tool Registry**: MCP 호환 도구 시스템 + 샌드박스 실행
- **Prompt Versioning**: 불변 버전 관리 + 템플릿 렌더링
- **Observability**: OpenTelemetry 트레이싱 + 구조화 로깅

## Quick Start

```bash
cd ai-agent-platform
make dev              # install dependencies
cp .env.example .env  # configure API keys
make test             # run tests
make serve            # start API server
```

## Documentation

| Document | Description |
|----------|-------------|
| [Architecture](docs/platform/architecture.md) | 시스템 아키텍처 및 데이터 플로우 |
| [Getting Started](docs/platform/getting-started.md) | 설치 및 첫 실행 가이드 |
| [Model Providers](docs/platform/model-providers.md) | 프로바이더 추가 방법 |
| [Harness Guide](docs/platform/harness-guide.md) | 커스텀 하네스 개발 |
| [Eval Guide](docs/platform/eval-guide.md) | 평가 프레임워크 사용법 |
| [API Reference](docs/platform/api-reference.md) | REST/WebSocket API 명세 |
| [Roadmap](docs/platform/roadmap.md) | 개발 로드맵 및 작업 목록 |

## Tech Stack

- **Runtime**: Python 3.11+ / async-first
- **API**: FastAPI + WebSocket
- **LLM**: Anthropic Claude, OpenAI GPT, Google Gemini
- **Infra**: Docker Compose, Redis, GitHub Actions
- **Quality**: ruff, mypy, pytest, OpenTelemetry
