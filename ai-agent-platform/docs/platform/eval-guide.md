# Evaluation Guide

## 개요

평가 프레임워크는 **모델 × 하네스** 조합의 성능을 정량적으로 측정합니다.
CI/CD 파이프라인에 통합되어 품질 게이트 역할을 합니다.

## 평가 실행

### CLI

```bash
# 기본 설정으로 실행
make eval

# 커스텀 설정
python -m agent_platform.eval.runner \
  --config eval/configs/default_eval.yaml \
  --output eval/results/$(date +%Y%m%d).json

# CI 게이트 모드 (기준 미달 시 exit code 1)
python -m agent_platform.eval.runner \
  --config eval/configs/default_eval.yaml \
  --ci-gate
```

### 결과 형식

```json
{
  "summary": {
    "average_score": 0.8500,
    "pass_rate": 0.8000,
    "total_cost_usd": 0.1234,
    "total_tasks": 10,
    "passes_gate": true
  },
  "results": [
    {
      "task_id": "hello_world",
      "model": "claude-sonnet-4-20250514",
      "harness": "react",
      "scores": {"exact_match": 1.0, "test_pass": 1.0},
      "elapsed_s": 12.34,
      "cost_usd": 0.0012
    }
  ]
}
```

## 데이터셋 작성

JSONL 형식으로 `eval/datasets/`에 저장:

```jsonl
{
  "task_id": "unique_id",
  "description": "작업 설명 (에이전트가 받는 프롬프트)",
  "category": "bugfix",
  "difficulty": "medium",
  "expected_output": "기대 출력 (exact match용)",
  "test_command": "python -m pytest test_file.py",
  "files": {"initial.py": "초기 파일 내용"}
}
```

### 필드 설명

| 필드 | 필수 | 설명 |
|------|------|------|
| task_id | O | 고유 식별자 |
| description | O | 에이전트에게 전달되는 작업 설명 |
| category | X | 분류 (bugfix, algorithm, refactoring, testing) |
| difficulty | X | 난이도 (easy, medium, hard) |
| expected_output | X | 기대 출력 문자열 |
| test_command | X | 검증용 셸 커맨드 |
| files | X | 초기 파일 맵 {경로: 내용} |

## Scorers (채점기)

### 내장 Scorer

| Scorer | 설명 | 점수 기준 |
|--------|------|-----------|
| `exact_match` | 출력이 기대값과 정확히 일치 | 1.0 or 0.0 |
| `contains` | 출력에 기대 문자열 포함 | 1.0 or 0.0 |
| `regex_match` | 출력이 정규식 패턴 매치 | 1.0 or 0.0 |
| `test_pass` | 테스트 커맨드 exit code 0 | 1.0 or 0.0 |

### 커스텀 Scorer 추가

```python
from agent_platform.eval.scorers import ScorerRegistry, ScoreResult
from agent_platform.eval.datasets import EvalTask

async def my_scorer(task: EvalTask, output: str) -> ScoreResult:
    # 커스텀 채점 로직
    score = compute_quality(output)
    return ScoreResult(scorer_name="my_scorer", value=score, reason="...")

registry = ScorerRegistry()
registry.register("my_scorer", my_scorer)
```

## CI/CD 통합

### GitHub Actions Eval Gate

PR이 `eval/` 또는 `harness/` 코드를 수정하면 자동으로 평가가 실행됩니다.
평균 점수가 `min_score_threshold` 미만이면 CI가 실패합니다.

```yaml
# .github/workflows/eval-gate.yml에 이미 설정됨
# 결과는 PR 코멘트에 자동으로 게시
```

### 수동 트리거

GitHub Actions → Eval Gate → Run workflow에서 모델/하네스/임계값을 지정하여 실행 가능.

## 모델 비교 분석

같은 데이터셋에 대해 여러 모델을 비교:

```yaml
name: model_comparison
models:
  - claude-sonnet-4-20250514
  - gpt-4o
  - gemini-2.5-pro
harnesses:
  - react
scorers:
  - test_pass
```

결과 JSON에서 모델별 점수, 비용, 속도를 비교할 수 있습니다.
