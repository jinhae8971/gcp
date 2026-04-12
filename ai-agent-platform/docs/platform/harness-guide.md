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

### Architect
- **패턴**: 읽기 전용 도구로 설계 문서 생성
- **적합한 작업**: 신규 시스템 설계, API 스펙 작성, 리팩토링 전략 수립
- **정지 조건**: `DESIGN COMPLETE` 센티넬 또는 도구 호출 없을 때
- **특징**: `write_file`/`execute_command` 등 변경 도구 자동 필터링 → 환각 구현 방지
- **산출물**: Goals / Non-Goals / Constraints / Options / Chosen Approach / Module Boundaries / Test Strategy / Handoff Checklist 섹션의 마크다운 설계 문서

### Code Review
- **패턴**: 5차원 루브릭(Correctness, Security, Maintainability, Performance, Consistency) 기반 리뷰
- **적합한 작업**: PR 리뷰, 기존 코드 감사, 보안 점검
- **정지 조건**: `REVIEW COMPLETE` 센티넬
- **특징**: 읽기 전용 도구만 사용, 최종 권고는 `APPROVE | REQUEST_CHANGES | BLOCK` 중 하나
- **산출물**: Critical / Important / Suggestions / Positives 섹션 리포트

### Multi-File
- **패턴**: Discovery → Change Manifest → Execution → Verification 4단계
- **적합한 작업**: 대규모 리네이밍, 시그니처 변경, 프로젝트 전체 import 경로 수정
- **정지 조건**: 매니페스트의 모든 파일 처리 후 `REFACTOR COMPLETE`
- **특징**: 첫 응답에서 `{"manifest": [...]}` JSON을 추출해 상태를 추적, 매 iteration마다 현재 진행 상황을 시스템 메시지로 주입

```json
{"manifest": [
  {"path": "src/foo.py", "intent": "rename User → Account", "status": "pending"},
  {"path": "tests/test_foo.py", "intent": "update fixtures", "status": "pending"}
]}
```

### Debate
- **패턴**: Proposer(짝수 라운드) ↔ Critic(홀수 라운드) 교대, 최종 Judge가 결정
- **적합한 작업**: 아키텍처 선택, 트레이드오프 분석, 설계 리뷰
- **정지 조건**:
  - 양측 모두 `CONSENSUS REACHED` → 즉시 Judge 라운드로 점프
  - Judge 라운드에서 `DEBATE COMPLETE`
  - `MAX_DEBATE_ROUNDS = 6` 안전장치
- **특징**: 페르소나 다양성을 위해 temperature=0.3

### Human-in-the-Loop
- **패턴**: 위험한 도구 호출 전에 사람 승인 요청
- **적합한 작업**: 운영 환경 변경, DB 마이그레이션, 프로덕션 배포
- **모드**:
  - `ask`: 모든 도구 호출이 승인 필요
  - `allow_safe`: `RISKY_TOOLS`({`write_file`, `execute_command`, `delete_file`, `run_migration`, `deploy`})만 승인 필요
- **정지 조건**: `TASK COMPLETE` 센티넬
- **위험 탐지**: `execute_command`의 경우 `sudo`, `rm -`, `git push`, `curl -X POST`, `dd `, `mkfs` 등 패턴 추가 검사
- **거절 피드백**: 거절된 호출은 다음 prepare_request에 시스템 메시지로 주입 → 모델이 재시도/적응 가능

```python
async def my_approval(req: ApprovalRequest) -> ApprovalDecision:
    # Relay to UI/Slack/CLI and wait for human
    return ApprovalDecision(approved=True, reason="reviewed")

harness = HumanInLoopHarness(
    tool_definitions=tool_defs,
    approval_callback=my_approval,
    mode="allow_safe",
)
```

## 하네스 선택 가이드

| 작업 유형 | 권장 하네스 |
|---|---|
| 일반 코딩/버그 수정 | `react` |
| 대규모 신규 기능 | `plan_execute` |
| 시스템 설계 문서 | `architect` |
| PR 리뷰 | `code_review` |
| 프로젝트 전반 리팩토링 | `multi_file` |
| 아키텍처 의사결정 | `debate` |
| 운영 환경 변경 | `human_in_loop` |

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
  - architect
  - code_review
  - multi_file
scorers:
  - exact_match
  - test_pass
min_score_threshold: 0.7
```

```bash
python -m agent_platform.eval.runner --config eval/configs/harness_comparison.yaml
```

### 자동 비교 리포트

여러 하네스를 같은 데이터셋으로 돌린 뒤, `harness_compare`로 카테고리별
승자와 전체 승자를 한 번에 산출할 수 있습니다.

```python
from agent_platform.eval.harness_compare import (
    compare_harnesses, load_dataset_categories,
)

categories = load_dataset_categories("eval/datasets/coding_tasks.jsonl")
comparison = compare_harnesses(report, task_categories=categories)

print(comparison.to_markdown())     # 사람이 읽기 좋은 요약
comparison.save_json("runs/compare.json")
print(comparison.winner)            # 전체 최고 성능 하네스
print(comparison.best_per_category) # {"algorithm": "react", "design": "architect"}
```

출력에는 하네스별 평균 점수, 통과율, 평균 지연/비용, 샘플 수, 에러 수가
포함되며 마크다운 렌더링 시 카테고리별 승자에 🏆 마커가 표시됩니다.

## 설계 원칙

1. **시스템 프롬프트가 행동을 결정**: 하네스의 핵심은 `prepare_request()`에서 주입하는 시스템 프롬프트
2. **도구 선택도 하네스 책임**: 작업 단계에 따라 노출 도구 세트를 변경 가능
3. **정지 조건은 명확하게**: 무한 루프 방지를 위해 MAX_ITERATIONS 안전장치 존재 (기본 50회)
