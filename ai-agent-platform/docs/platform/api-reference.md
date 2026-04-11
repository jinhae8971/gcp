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

### Evaluation

#### Trigger Eval Run (planned)

```
POST /eval/run
```

**Request Body:**
```json
{
  "config_path": "eval/configs/default_eval.yaml",
  "models": ["claude-sonnet-4-20250514", "gpt-4o"],
  "harnesses": ["react"]
}
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
