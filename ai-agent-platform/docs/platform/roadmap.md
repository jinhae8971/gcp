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

## Phase 3: Advanced Harness Patterns

다양한 에이전트 아키텍처 실험

- [ ] Architect harness (설계 전문 에이전트)
- [ ] Code Review harness (리뷰 특화)
- [ ] Multi-file harness (대규모 리팩토링)
- [ ] Debate harness (두 에이전트가 토론하며 해결)
- [ ] Human-in-the-loop harness (승인 기반 실행)
- [ ] 하네스 성능 비교 자동 리포트

---

## Phase 4: Production Hardening

운영 환경 안정성 확보

- [ ] gVisor / Firecracker 기반 샌드박스 격리
- [ ] API 인증/인가 (JWT + RBAC)
- [ ] Rate limiting (사용자별/팀별 한도)
- [ ] 비용 알림 및 예산 제한
- [ ] 에러 복구 및 재시도 전략 고도화
- [ ] 로그 집약 (ELK/Loki)
- [ ] Grafana 메트릭 대시보드

---

## Phase 5: Team & Scale

팀 단위 협업 및 확장

- [ ] 멀티 테넌트 지원
- [ ] 팀별 프롬프트/모델 설정 관리
- [ ] Agent Teams (복수 에이전트 협업, git worktree 격리)
- [ ] Slack/Teams 알림 연동
- [ ] 사용량 리포트 (팀별/프로젝트별)
- [ ] Self-hosted LLM 지원 (vLLM, Ollama 어댑터)
- [ ] Web Dashboard UI (React/Next.js)

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
