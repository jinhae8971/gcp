.PHONY: help install dev test lint format typecheck eval docs serve clean

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

install: ## Install production dependencies
	pip install -e .

dev: ## Install with all dev dependencies
	pip install -e ".[dev,eval,docs]"
	pre-commit install

test: ## Run unit tests
	pytest tests/unit -v --tb=short

test-all: ## Run all tests (unit + integration)
	pytest tests/ -v --tb=short

test-cov: ## Run tests with coverage report
	pytest tests/unit --cov=agent_platform --cov-report=html --cov-report=term-missing

lint: ## Run linter
	ruff check src/ tests/

format: ## Auto-format code
	ruff format src/ tests/
	ruff check --fix src/ tests/

typecheck: ## Run type checker
	mypy src/agent_platform/

eval: ## Run evaluation suite
	python -m agent_platform.eval.runner --config eval/configs/default_eval.yaml

docs: ## Build documentation
	mkdocs build

serve: ## Start API server (development)
	uvicorn agent_platform.api.server:app --reload --host 0.0.0.0 --port 8000

docker-up: ## Start all services via Docker Compose
	docker compose up -d --build

docker-down: ## Stop all services
	docker compose down

clean: ## Remove build artifacts
	rm -rf dist/ build/ *.egg-info .pytest_cache .mypy_cache htmlcov/ .ruff_cache
