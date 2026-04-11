# Getting Started

## Prerequisites

- Python 3.11+
- Docker & Docker Compose (optional, for containerized deployment)
- 최소 1개의 LLM Provider API 키 (Anthropic / OpenAI / Google)

## Quick Start

### 1. 로컬 개발 환경 설정

```bash
cd ai-agent-platform

# 개발 의존성 포함 설치
make dev

# 환경 변수 설정
cp .env.example .env
# .env 파일에 API 키 입력
```

### 2. 테스트 실행

```bash
# 유닛 테스트
make test

# 린트 + 타입 체크
make lint
make typecheck

# 커버리지 리포트
make test-cov
```

### 3. API 서버 실행

```bash
# 개발 모드 (자동 리로드)
make serve

# 또는 직접 실행
uvicorn agent_platform.api.server:app --reload --port 8000
```

서버가 시작되면:
- API Docs: http://localhost:8000/docs (Swagger UI)
- Health Check: http://localhost:8000/health

### 4. Docker Compose로 실행

```bash
# 전체 스택 시작 (API + Eval Worker + Redis)
make docker-up

# 종료
make docker-down
```

## 첫 번째 에이전트 세션

### REST API로 실행

```bash
# 세션 생성
curl -X POST http://localhost:8000/sessions \
  -H "Content-Type: application/json" \
  -d '{"model_id": "claude-sonnet-4-20250514", "harness_id": "react"}'

# 사용 가능한 모델 조회
curl http://localhost:8000/models | python -m json.tool

# 하네스 패턴 조회
curl http://localhost:8000/harnesses | python -m json.tool
```

### 평가 실행

```bash
# 기본 설정으로 평가 실행
make eval

# 또는 직접 실행
python -m agent_platform.eval.runner \
  --config eval/configs/default_eval.yaml \
  --output eval/results/latest.json
```

## 프로젝트 구조

```
ai-agent-platform/
├── src/agent_platform/     # 소스 코드
│   ├── core/               # 에이전트 루프, 오케스트레이터, 세션
│   ├── models/             # 모델 게이트웨이 + 프로바이더 어댑터
│   ├── tools/              # 도구 레지스트리 + 빌트인 도구
│   ├── harness/            # 교체 가능한 하네스 패턴
│   ├── eval/               # 평가 프레임워크
│   ├── prompts/            # 프롬프트 버전 관리
│   ├── observability/      # 트레이싱, 로깅
│   ├── api/                # FastAPI 서버
│   └── config/             # Pydantic 설정
├── tests/                  # 테스트
├── eval/                   # 평가 데이터셋 + 설정
├── docs/platform/          # 개발자 문서
├── .github/workflows/      # CI/CD
├── pyproject.toml          # 프로젝트 설정
├── Dockerfile              # 컨테이너 빌드
└── docker-compose.yml      # 전체 스택 오케스트레이션
```

## 다음 단계

- [Architecture](architecture.md) - 시스템 아키텍처 상세
- [Model Providers](model-providers.md) - 새 프로바이더 추가 방법
- [Harness Guide](harness-guide.md) - 커스텀 하네스 만들기
- [Eval Guide](eval-guide.md) - 평가 프레임워크 사용법
