# Development Roadmap

## Phase 1: Foundation (Current)

핵심 인프라 구축 - 에이전트 루프가 실제로 돌아가는 최소 기능 제품(MVP)

### Completed
- [x] 프로젝트 스캐폴딩 및 빌드 시스템 (pyproject.toml, Makefile)
- [x] Core agent loop 설계 (message → LLM → tool → feedback cycle)
- [x] Multi-agent orchestrator (Supervisor, Parallel, Pipeline 패턴)
- [x] Session management (상태, 토큰, 비용 추적)
- [x] Model Gateway + Circuit Breaker + Fallback chain
- [x] Provider adapters (Anthropic, OpenAI, Google)
- [x] Model registry + pricing catalog
- [x] Tool registry (등록, 실행, 병렬 분류)
- [x] Built-in tools (file ops, shell execution)
- [x] Harness system (BaseHarness + ReAct + Plan-Execute)
- [x] Eval framework (runner, datasets, scorers)
- [x] Prompt versioning registry
- [x] Observability (OpenTelemetry tracer, structlog)
- [x] FastAPI server skeleton (REST + WebSocket)
- [x] CI/CD pipelines (lint/test/eval-gate/deploy)
- [x] Docker + docker-compose
- [x] Developer documentation (5 pages)
- [x] Sample eval dataset (5 tasks)

### Remaining for Phase 1
- [ ] Agent loop ↔ Gateway ↔ Tools 통합 테스트
- [ ] Session persistence (Redis 저장/복원)
- [ ] WebSocket 스트리밍 실제 연결
- [ ] MCP client 구현 (외부 도구 연결)
- [ ] Integration test suite

---

## Phase 2: Evaluation & Comparison

데이터 기반 의사결정을 위한 평가 파이프라인 고도화

- [ ] LLM-as-Judge scorer 구현 (Claude가 다른 모델 출력 평가)
- [ ] 평가 결과 대시보드 (HTML 리포트 자동 생성)
- [ ] 모델별 성능/비용/속도 비교 차트
- [ ] SWE-Bench 스타일 eval dataset 확대 (50+ tasks)
- [ ] Prompt A/B 테스트 프레임워크
- [ ] 평가 결과 히스토리 관리 (트렌드 추적)
- [ ] eval worker 비동기 작업 큐 (Redis + worker)

---

## Phase 3: Advanced Harness Patterns ✅

다양한 에이전트 아키텍처 실험

- [x] Architect harness (설계 전문 에이전트, read-only 도구)
- [x] Code Review harness (5차원 루브릭 리뷰)
- [x] Multi-file harness (manifest 기반 대규모 리팩토링)
- [x] Debate harness (Proposer/Critic/Judge 3-phase 토론)
- [x] Human-in-the-loop harness (ask / allow_safe 2모드 승인)
- [x] 하네스 성능 비교 자동 리포트 (per-category winner, markdown/JSON)

---

## Phase 4: Production Hardening ✅

운영 환경 안정성 확보

- [x] Sandbox 실행 프로파일 (`security/sandbox_policy.py`: dev/standard/hardened/isolated_vm, gVisor/Firecracker 지원)
- [x] API 인증/인가 (`security/auth.py`: HS256 JWT + RBAC 와일드카드 지원)
- [x] Rate limiting (`security/rate_limit.py`: 토큰 버킷, 티어별 정책)
- [x] 비용 알림 및 예산 제한 (`security/budget.py`: alert/exceeded state + hard_stop)
- [x] 에러 복구 및 재시도 전략 (Gateway circuit breaker + fallback 체인)
- [x] 로그 집약 (structlog JSON 포맷 → ELK/Loki 호환)
- [x] Prometheus 메트릭 (`observability/metrics.py`: Counter/Gauge/Histogram, `/metrics` 텍스트 포맷)

---

## Phase 5: Team & Scale ✅

팀 단위 협업 및 확장

- [x] 멀티 테넌트 지원 (`tenancy/tenant.py`: TenantScopedSessionStore로 cross-tenant 차단)
- [x] 팀별 프롬프트/모델 설정 (`tenancy/team_config.py`: JSON/YAML 로더, 멤버십 해석)
- [x] Agent Teams (`teams/agent_teams.py`: git worktree 기반 병렬 에이전트 협업)
- [x] Slack 알림 (`notifier/slack.py`: Webhook + severity 색상 매핑)
- [x] 사용량 리포트 (`tenancy/usage_report.py`: 팀/모델/프로젝트별 JSON/CSV)
- [x] Self-hosted LLM 지원 (`models/providers/local.py`: vLLM/Ollama OpenAI 호환)
- [x] Web Dashboard (eval HTML dashboard via `/eval/dashboard`)

---

## Architecture Decision Records

| ADR | Decision | Rationale |
|-----|----------|-----------|
| ADR-001 | Python 3.11+ async-first | 모든 LLM SDK가 Python 우선 지원 |
| ADR-002 | FastAPI for API server | async 네이티브 + 자동 OpenAPI 문서 |
| ADR-003 | Pydantic for all data contracts | 타입 안전성 + 직렬화 |
| ADR-004 | Provider abstraction over LiteLLM direct | 세밀한 제어 필요 (circuit breaker, cost tracking) |
| ADR-005 | Harness as pluggable strategy | 신규 패턴 실험을 eval로 비교 가능 |
| ADR-006 | JSONL for eval datasets | 한 줄 = 한 태스크, git diff 친화적 |
| ADR-007 | OpenTelemetry for tracing | 벤더 중립 표준, 다양한 백엔드 지원 |
| ADR-008 | CI eval gate on PR | 프롬프트/하네스 변경이 품질 하락을 유발하지 않도록 보장 |
