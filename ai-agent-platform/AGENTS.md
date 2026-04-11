# Agent Platform - Agent Instructions

## Project Overview
In-house agentic coding platform for evaluating and orchestrating multiple LLM providers
and harness architectures. Python 3.11+, FastAPI backend, async-first design.

## Build & Test
```bash
make dev          # install all dependencies
make test         # run unit tests
make lint         # ruff linter
make typecheck    # mypy strict mode
make eval         # run model evaluation suite
```

## Architecture
- `src/agent_platform/core/` - Agent loop, orchestrator, session management
- `src/agent_platform/models/` - Multi-provider model gateway (LiteLLM-based)
- `src/agent_platform/tools/` - MCP-compatible tool registry
- `src/agent_platform/harness/` - Pluggable harness patterns (ReAct, Plan-Execute, etc.)
- `src/agent_platform/eval/` - Evaluation framework with CI gate integration
- `src/agent_platform/api/` - FastAPI REST + WebSocket server

## Conventions
- All async functions use `async def`, never blocking I/O in async context
- Pydantic models for all data contracts
- Structured logging via structlog
- Type annotations required on all public functions
- Tests mirror source layout: `src/agent_platform/core/agent_loop.py` -> `tests/unit/test_agent_loop.py`
