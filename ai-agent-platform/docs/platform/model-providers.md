# Model Providers Guide

## 지원 모델 현황

| Provider | Model | Tier | Context | Input $/1M | Output $/1M |
|----------|-------|------|---------|------------|-------------|
| Anthropic | claude-opus-4 | Frontier | 200K | $15.00 | $75.00 |
| Anthropic | claude-sonnet-4 | Standard | 200K | $3.00 | $15.00 |
| OpenAI | gpt-4o | Standard | 128K | $2.50 | $10.00 |
| OpenAI | o3 | Frontier | 200K | $10.00 | $40.00 |
| Google | gemini-2.5-pro | Standard | 1M | $1.25 | $10.00 |
| Google | gemini-2.5-flash | Fast | 1M | $0.15 | $0.60 |

## 새 프로바이더 추가 방법

### 1. Provider Adapter 구현

`src/agent_platform/models/providers/` 에 새 파일 생성:

```python
from agent_platform.models.providers.base import (
    BaseProvider, ChatRequest, ChatResponse, StreamChunk, UsageInfo,
)

class NewProvider(BaseProvider):
    provider_name = "new_provider"
    supported_models = ["new-model-v1", "new-model-v2"]

    def __init__(self, api_key: str) -> None:
        # 클라이언트 초기화

    async def chat(self, model: str, request: ChatRequest) -> ChatResponse:
        # 채팅 완성 API 호출 → ChatResponse로 변환

    async def stream_chat(self, model: str, request: ChatRequest):
        # 스트리밍 API 호출 → StreamChunk yield

    async def health_check(self) -> bool:
        # 프로바이더 연결 상태 확인
```

### 2. Gateway에 모델 매핑 등록

`src/agent_platform/models/gateway.py`의 `_MODEL_PROVIDER_MAP`에 추가:

```python
_MODEL_PROVIDER_MAP["new-model-v1"] = "new_provider"
```

### 3. Model Registry에 카탈로그 추가

`src/agent_platform/models/registry.py`의 `MODEL_CATALOG`에 추가:

```python
"new-model-v1": ModelInfo(
    model_id="new-model-v1",
    provider="new_provider",
    tier=ModelTier.STANDARD,
    max_context=128_000,
    max_output=8_192,
    capabilities=[Capability.CODE_GENERATION, Capability.TOOL_USE],
    input_cost_per_m=2.0,
    output_cost_per_m=8.0,
    description="New model description",
),
```

### 4. 테스트 추가

`tests/unit/test_new_provider.py` 작성 후 `make test` 실행.

## Gateway 기능

### Circuit Breaker
- 3회 연속 실패 → 해당 프로바이더 60초 차단
- 차단 해제 후 1회 시도 (Half-Open)
- 성공 시 완전 복구

### Fallback Chain
```
Primary (claude-sonnet-4)
    → Fallback 1 (gpt-4o)
    → Fallback 2 (gemini-2.5-pro)
    → Error
```

### 비용 추적
- 모든 API 호출에 대해 input/output 토큰 수와 예상 비용 기록
- 세션 단위 누적 비용 추적
- eval 리포트에 비용 포함
