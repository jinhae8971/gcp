# Convenience shortcuts for the local Docker dev environment.
# Run `make` (no target) for the list.

.PHONY: help up down restart logs logs-data ps refresh refresh-kospi shell-web shell-data shell-gen build-pull clean

help: ## 사용 가능한 명령 목록
	@awk 'BEGIN {FS = ":.*##"} /^[a-zA-Z_-]+:.*##/ {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)
	@echo ""
	@echo "  접속:"
	@echo "    - 메인 인덱스:        http://localhost:$${GMM_WEB_PORT:-8080}/"
	@echo "    - KOSPI Intel:        http://localhost:$${GMM_WEB_PORT:-8080}/Dashboard.html"
	@echo "    - Global Money MOVE:  http://localhost:$${GMM_WEB_PORT:-8080}/global_money_flow.html"
	@echo ""
	@echo "  키 설정:  cp .env.example .env  → 값 입력"

up: ## 두 대시보드 띄우기 (data + web 백그라운드)
	docker compose up -d
	@echo ""
	@echo "  ✓ http://localhost:$${GMM_WEB_PORT:-8080}/"
	@echo "  로그: make logs / make logs-data"
	@echo "  정리: make down"

down: ## 정리 (컨테이너 + 네트워크 제거; 볼륨 유지)
	docker compose down

restart: ## web + data 재시작
	docker compose restart

logs: ## nginx 로그 (Ctrl+C 로 종료)
	docker compose logs -f web

logs-data: ## KOSPI 데이터 5분 cron 로그 (Ctrl+C 로 종료)
	docker compose logs -f data

ps: ## 컨테이너 상태
	docker compose ps

refresh: ## Global Money MOVE AI 번들 1회 갱신 (.env 의 ANTHROPIC_API_KEY 필요)
	@if [ ! -f .env ] && [ -z "$$ANTHROPIC_API_KEY" ]; then \
		echo "✗ .env 파일이 없습니다. 먼저: cp .env.example .env  → 키 입력"; \
		exit 1; \
	fi
	docker compose --profile gmm run --rm gmm-generator

refresh-kospi: ## KOSPI Intel 데이터 즉시 재생성 (data 컨테이너 재시작)
	docker compose restart data

shell-web: ## 웹 컨테이너 안에서 sh
	docker compose exec web sh

shell-data: ## KOSPI 데이터 컨테이너 안에서 bash
	docker compose exec data bash

shell-gen: ## Global Money MOVE 생성기 컨테이너 안에서 bash (1회성)
	docker compose --profile gmm run --rm --entrypoint bash gmm-generator

build-pull: ## 베이스 이미지 최신본 + 로컬 이미지 재빌드
	docker compose pull
	docker compose build

clean: ## 컨테이너 + 이미지 + 볼륨 모두 제거 (캐시 날아감)
	docker compose --profile gmm down -v --rmi local
