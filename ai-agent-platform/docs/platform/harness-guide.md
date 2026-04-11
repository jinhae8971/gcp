# Harness Guide

## 하네스란?

하네스(Harness)는 에이전트 루프의 **행동 패턴**을 정의합니다.
같은 모델이라도 하네스에 따라 전혀 다른 방식으로 작업을 수행합니다.

## 내장 하네스

### ReAct (기본값)
- **패턴**: Reasoning + Acting 교대 반복
- **적합한 작업**: 범용 코딩, 버그 수정, 탐색적 작업
- **정지 조건**: 모델이 도구 호출 없이 텍스트만 응답할 때

```
User: "Fix the bug in auth.py"
→ [Reason] "Let me read auth.py first"
→ [Act] read_file("auth.py")
→ [Observe] file contents
→ [Reason] "I see the issue on line 42"
→ [Act] write_file("auth.py", fixed_content)
→ [Observe] "Written successfully"
→ [Final] "Fixed the authentication bug..."
```

### Plan-Execute
- **패턴**: 먼저 계획 수립, 그 다음 단계별 실행
- **적합한 작업**: 대규모 리팩토링, 신규 기능 구현, 멀티 파일 작업
- **정지 조건**: 모든 계획 단계가 완료될 때

```
User: "Add user authentication to the API"
→ [Plan] {"plan": [
    {"step": 1, "action": "Create User model"},
    {"step": 2, "action": "Add auth middleware"},
    {"step": 3, "action": "Create login endpoint"},
    {"step": 4, "action": "Add tests"}
  ]}
→ [Execute Step 1] ...
→ [Execute Step 2] ...
→ [Execute Step 3] ...
→ [Execute Step 4] ...
→ [Summary] "Authentication system implemented..."
```

## 커스텀 하네스 만들기

### 1. BaseHarness 상속

```python
from agent_platform.harness.base import BaseHarness, LLMRequest
from agent_platform.core.session import AgentSession
from agent_platform.models.providers.base import ChatResponse

class MyCustomHarness(BaseHarness):
    harness_id = "my_custom"
    description = "Custom harness pattern for specific use case"

    def prepare_request(self, session: AgentSession) -> LLMRequest:
        # 시스템 프롬프트 구성 + 메시지 포맷팅 + 도구 선택
        return LLMRequest(messages=[...], tool_definitions=[...])

    def should_stop(self, session: AgentSession, response: ChatResponse) -> bool:
        # 종료 조건 판단 로직
        return some_condition
```

### 2. 등록 & 사용

API 서버의 `list_harnesses`에 추가하고, eval config에서 비교 대상에 포함.

## 하네스 비교 평가

```yaml
# eval/configs/harness_comparison.yaml
name: harness_comparison
models:
  - claude-sonnet-4-20250514
harnesses:
  - react
  - plan_execute
  - my_custom
scorers:
  - exact_match
  - test_pass
min_score_threshold: 0.7
```

```bash
python -m agent_platform.eval.runner --config eval/configs/harness_comparison.yaml
```

## 설계 원칙

1. **시스템 프롬프트가 행동을 결정**: 하네스의 핵심은 `prepare_request()`에서 주입하는 시스템 프롬프트
2. **도구 선택도 하네스 책임**: 작업 단계에 따라 노출 도구 세트를 변경 가능
3. **정지 조건은 명확하게**: 무한 루프 방지를 위해 MAX_ITERATIONS 안전장치 존재 (기본 50회)
