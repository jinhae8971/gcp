# API Reference

## Base URL

```
http://localhost:8000
```

## Endpoints

### Health Check

```
GET /health
```

**Response:**
```json
{"status": "ok", "providers": {"anthropic": true, "openai": true}}
```

---

### Sessions

#### Create Session

```
POST /sessions
```

**Request Body:**
```json
{
  "model_id": "claude-sonnet-4-20250514",
  "harness_id": "react",
  "tools": ["read_file", "write_file", "execute_command"]
}
```

**Response:**
```json
{
  "session_id": "a1b2c3d4e5f6",
  "model_id": "claude-sonnet-4-20250514",
  "harness_id": "react",
  "status": "idle"
}
```

#### Send Message (planned)

```
POST /sessions/{session_id}/message
```

**Request Body:**
```json
{"content": "Fix the bug in auth.py"}
```

**Response:**
```json
{
  "role": "assistant",
  "content": "I'll look at auth.py...",
  "tool_calls": [{"name": "read_file", "arguments": {"path": "auth.py"}}]
}
```

---

### Models

#### List Models

```
GET /models
```

**Response:**
```json
[
  {
    "model_id": "claude-sonnet-4-20250514",
    "provider": "anthropic",
    "tier": "standard",
    "description": "Best price-performance ratio for coding agents"
  }
]
```

---

### Harnesses

#### List Harnesses

```
GET /harnesses
```

**Response:**
```json
[
  {"harness_id": "react", "description": "ReAct pattern: interleaved reasoning and tool use"},
  {"harness_id": "plan_execute", "description": "Two-phase: plan first, then execute step by step"}
]
```

---

### Tools

#### List Tools

```
GET /tools
```

**Response:**
```json
[
  {"name": "read_file", "description": "Read a file from the workspace", "parallel_safe": true},
  {"name": "execute_command", "description": "Execute a shell command", "parallel_safe": false}
]
```

---

### Evaluation

#### Run Eval Suite

```
POST /eval/run
```

**Request Body:**
```json
{
  "config_path": "eval/configs/default_eval.yaml",
  "name": "model_comparison",
  "dataset_path": "eval/datasets/coding_tasks.jsonl",
  "models": ["claude-sonnet-4-20250514", "gpt-4o"],
  "harnesses": ["react"],
  "scorers": ["exact_match", "test_pass"],
  "min_score_threshold": 0.7,
  "max_concurrent": 4,
  "timeout_per_task": 300
}
```

> `config_path`가 있으면 YAML을 먼저 로드하고 나머지 필드로 오버라이드합니다.

**Response:**
```json
{
  "config": {"name": "model_comparison", "models": [...], "harnesses": [...]},
  "summary": {
    "average_score": 0.8500,
    "pass_rate": 0.8000,
    "total_cost_usd": 0.1234,
    "total_tasks": 10,
    "passes_gate": true
  },
  "results": [...],
  "history_file": "eval/results/history/model_comparison_20260411_120000_123456.json"
}
```

#### List Eval History

```
GET /eval/history?name=default&limit=20
```

**Response:**
```json
{
  "runs": [
    {
      "file": "default_20260411_120000_123456.json",
      "name": "default",
      "completed_at": "2026-04-11T12:00:00Z",
      "summary": {"average_score": 0.85, "pass_rate": 0.80, "passes_gate": true}
    }
  ]
}
```

#### Get Specific Run

```
GET /eval/history/{filename}
```

**Response:** 저장된 평가 결과 전체 JSON

#### Get Score Trend

```
GET /eval/trend?name=default&limit=30
```

**Response:** 차트용 트렌드 데이터 배열 (oldest-first)

```json
[
  {"file": "...", "name": "default", "completed_at": "...", "summary": {...}},
  ...
]
```

#### Compare Last Two Runs

```
GET /eval/compare?name=default
```

**Response:**
```json
{
  "current": {"file": "...", "summary": {...}},
  "previous": {"file": "...", "summary": {...}},
  "score_delta": 0.0500,
  "pass_rate_delta": 0.1000,
  "cost_delta": -0.0020,
  "regression": false
}
```

> `regression`이 `true`이면 5% 이상 점수 하락을 의미합니다.

#### Run A/B Test

```
POST /eval/ab-test
```

**Request Body:**
```json
{
  "name": "prompt_v2_test",
  "variant_a": {
    "name": "baseline",
    "prompt_name": "default_system",
    "prompt_version": 1,
    "harness_id": "react"
  },
  "variant_b": {
    "name": "candidate",
    "prompt_name": "default_system",
    "prompt_version": 2,
    "harness_id": "react"
  },
  "dataset_path": "eval/datasets/coding_tasks.jsonl",
  "model": "claude-sonnet-4-20250514",
  "scorers": ["exact_match", "test_pass"],
  "num_runs": 3
}
```

**Response:**
```json
{
  "experiment": "prompt_v2_test",
  "winner": "B",
  "confidence": 0.9723,
  "variant_a": {"name": "baseline", "mean_score": 0.72, "std_score": 0.15, "n_samples": 30},
  "variant_b": {"name": "candidate", "mean_score": 0.81, "std_score": 0.12, "n_samples": 30},
  "deltas": {"score": 0.09, "cost_usd": 0.015, "latency_s": 2.3},
  "completed_at": "2026-04-11T12:05:00Z"
}
```

#### List Scorers

```
GET /eval/scorers
```

**Response:**
```json
["exact_match", "contains", "regex_match", "test_pass", "code_quality"]
```

#### Get Dashboard HTML

```
GET /eval/dashboard?name=default
```

**Response:** Self-contained HTML dashboard (Content-Type: text/html)

#### Generate Dashboard

```
POST /eval/dashboard
```

평가를 실행하고 대시보드를 생성합니다. Request body는 `POST /eval/run`과 동일합니다.

**Response:**
```json
{"status": "ok", "dashboard_path": "eval/results/dashboard.html"}
```

---

### WebSocket

#### Streaming Agent Session

```
WS /ws/{session_id}
```

**Send:**
```json
{"content": "Create a hello world script"}
```

**Receive Events:**
```json
{"type": "iteration_start", "iteration": 1}
{"type": "token", "content": "I'll"}
{"type": "token", "content": " create"}
{"type": "tool_calls", "calls": [...]}
{"type": "tool_result", "result": {...}}
{"type": "complete", "iterations": 3}
```
