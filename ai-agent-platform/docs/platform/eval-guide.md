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

결과 JSON에서 모델별 점수, 비용, 속도를 비교할 수 있��니다.

## HTML 대시보드

평가 결과를 인터랙티브 HTML 대시보드로 확인할 수 있습니다.

```bash
# 평가 실행 + 대시보드 생성
python -m agent_platform.eval.runner \
  --config eval/configs/default_eval.yaml \
  --dashboard

# 히스토리 저장 + 이전 실행과 비교
python -m agent_platform.eval.runner \
  --config eval/configs/default_eval.yaml \
  --history --compare --dashboard
```

대시보드에 포함되는 정보:
- **Score Cards**: 평균 점수, 합격률, 총 비용, CI 게이트 상태
- **Model × Harness 비교 차트**: 조합별 평균 점수 바 차트
- **Per-Task 결과 테이블**: 개별 태스크별 점수, 시간, 비용, 에러
- **Score Trend Sparkline**: 시간에 따른 점수 변화 추이

### API를 통한 대시보드

```bash
# 최근 결과로 대시보드 HTML 가져오기
curl http://localhost:8000/eval/dashboard

# 특정 이름 필터로 조회
curl http://localhost:8000/eval/dashboard?name=model_comparison
```

## 평가 히스토리 & 회귀 감지

모든 평가 결과는 `eval/results/history/`에 타임스탬프 JSON 파일로 저장됩니다.

### 히스토리 관리

```python
from agent_platform.eval.history import EvalHistory

history = EvalHistory()

# 최근 실행 목록
runs = history.list_runs(name_filter="model_comparison", limit=10)

# 트렌드 데이터 (차트용, oldest-first)
trend = history.get_trend(name_filter="model_comparison")

# 최근 2회 비교 (CI 회귀 감지)
comparison = history.compare_last_two()
if comparison and comparison["regression"]:
    print("WARNING: 5% 이상 점수 하락 감지!")

# 오래된 히스토리 정리
history.cleanup_old(keep=100)
```

### API를 통한 히스토리 조회

```bash
# 히스토리 목록
curl http://localhost:8000/eval/history?name=default&limit=20

# 특정 실행 상세 조회
curl http://localhost:8000/eval/history/default_20260411_120000_123456.json

# 트렌드 데이터
curl http://localhost:8000/eval/trend?name=default

# 최근 2회 비교
curl http://localhost:8000/eval/compare?name=default
```

## A/B 테스트 (Prompt/Harness 비교)

두 개의 프롬프트 변형이나 하네스 설정을 통계적으로 비교합니다.
Welch's t-test를 사용하여 95% 신뢰구간에서 승자를 결정합니다.

### 프로그래밍 방식

```python
from agent_platform.eval.ab_testing import ABExperiment, ABRunner, VariantConfig

experiment = ABExperiment(
    name="system_prompt_v2_test",
    variant_a=VariantConfig(
        name="baseline",
        prompt_name="default_system",
        prompt_version=1,
    ),
    variant_b=VariantConfig(
        name="candidate",
        prompt_name="default_system",
        prompt_version=2,
    ),
    dataset_path="eval/datasets/coding_tasks.jsonl",
    model="claude-sonnet-4-20250514",
    scorers=["exact_match", "test_pass"],
    num_runs=3,  # 반복 횟수 (분산 감소)
)

runner = ABRunner()
result = await runner.run(experiment)

print(f"Winner: {result.winner}")        # "A", "B", or "tie"
print(f"Confidence: {result.confidence:.2%}")
print(f"Score delta: {result.score_delta:+.4f}")
```

### API를 통한 A/B 테스트

```bash
curl -X POST http://localhost:8000/eval/ab-test \
  -H "Content-Type: application/json" \
  -d '{
    "name": "react_vs_plan_execute",
    "variant_a": {"name": "ReAct", "harness_id": "react"},
    "variant_b": {"name": "PlanExec", "harness_id": "plan_execute"},
    "dataset_path": "eval/datasets/coding_tasks.jsonl",
    "model": "claude-sonnet-4-20250514",
    "num_runs": 2
  }'
```

**응답 예시:**
```json
{
  "experiment": "react_vs_plan_execute",
  "winner": "B",
  "confidence": 0.9723,
  "variant_a": {"name": "ReAct", "mean_score": 0.7200, "std_score": 0.1500, "n_samples": 60},
  "variant_b": {"name": "PlanExec", "mean_score": 0.8100, "std_score": 0.1200, "n_samples": 60},
  "deltas": {"score": 0.0900, "cost_usd": 0.0150, "latency_s": 2.30}
}
```

## LLM-as-Judge 채점

모델을 사용하여 다른 모델의 출력을 평가합니다. 4가지 차원으로 점수를 매깁니다:

| 차원 | 설명 |
|------|------|
| correctness | 코드가 태스크를 올바르게 해결하는가? |
| completeness | 엣지 케이스와 요구사항을 모두 다루는가? |
| code_quality | 코드가 깨끗하고 가독성이 좋은가? |
| efficiency | 솔루션이 효율적인가? |

### 사용법

```python
from agent_platform.eval.scorers import create_llm_judge_scorer, ScorerRegistry

# Gateway를 통해 LLM Judge 생성
scorer = create_llm_judge_scorer(gateway, judge_model="claude-sonnet-4-20250514")

# 레지스트리에 등록
registry = ScorerRegistry()
registry.register("llm_judge", scorer)

# 이후 eval 설정에서 "llm_judge" scorer를 사용
```

### Pairwise 비교

두 모델의 출력을 직접 비교하는 head-to-head 채점:

```python
from agent_platform.eval.scorers import create_pairwise_scorer

compare = create_pairwise_scorer(gateway, judge_model="claude-sonnet-4-20250514")
result = await compare(task, output_a, "model-a", output_b, "model-b")
# {"winner": "B", "reason": "...", "confidence": 0.85}
```

## Eval Worker (비동기 백그라운드 실행)

대규모 평가를 Redis 큐를 통해 비동기로 실행합니다.

### 아키텍처

```
API → LPUSH(eval_jobs) → Redis → BRPOP → Eval Worker → History + Dashboard
                                              ↓
                                   SETEX(eval_result:{job_id})
                                              ↓
                                   API polling GET /eval/result/{job_id}
```

### Worker 실행

```bash
# Docker Compose (권장)
docker compose up eval-worker

# 직접 실행
python -m agent_platform.eval.worker
```

### Job 제출

```python
from agent_platform.eval.worker import EvalWorker

job_id = await EvalWorker.submit_job(
    redis_url="redis://localhost:6379/0",
    config={"name": "nightly", "models": ["claude-sonnet-4-20250514"]},
)

# 결과 폴링
result = await EvalWorker.get_result(redis_url, job_id)
```

## 확장 데이터셋

`eval/datasets/coding_tasks.jsonl`에 30개의 평가 태스크가 포함되어 있습니다:

| 카테고리 | 태스크 수 | 설명 |
|----------|-----------|------|
| basic | 1 | Hello World 등 기본 작업 |
| algorithm | 9 | 문자열 반전, 피보나치, 이분탐색 등 |
| bugfix | 4 | Off-by-one, null check, race condition 수정 |
| testing | 2 | pytest 테스트 작성 |
| refactoring | 3 | 클래스 변환, 함수 분리, 타입 힌트 |
| design_pattern | 4 | Decorator, Context Manager, Singleton, EventEmitter |
| data_processing | 2 | CSV 파서, JSON Flatten |
| data_structure | 3 | LRU Cache, Linked List, Trie |
| async | 1 | Async Batch Processor |
| system_design | 1 | Rate Limiter |

### 난이도 분포

- **easy**: 11 tasks
- **medium**: 13 tasks
- **hard**: 6 tasks
