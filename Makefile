# Common development tasks. Run `make help` for the list.
# Python tasks use the active interpreter; create a virtualenv first (python3 -m venv .venv && . .venv/bin/activate).

PYTHON ?= python3
COMPOSE ?= docker compose -f platform/compose.yaml
WEB := npm --prefix platform/web
PY_SOURCES := platform/backend poc platform/scripts

.DEFAULT_GOAL := help
.PHONY: help install lint format test test-backend test-poc test-web build check up down logs seed logins verify migrate prod-config

help: ## Show this help
	@awk 'BEGIN {FS = ":.*## "} /^[a-zA-Z_-]+:.*## / {printf "  \033[1m%-14s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

install: ## Install backend/POC development dependencies and frontend packages
	$(PYTHON) -m pip install -r platform/backend/requirements-dev.txt -r poc/requirements.txt
	$(WEB) ci --no-audit --no-fund

lint: ## Lint and type-check Python and frontend code without changing files
	ruff check $(PY_SOURCES)
	ruff format --check $(PY_SOURCES)
	$(WEB) run typecheck
	$(WEB) run lint
	$(WEB) run format:check

format: ## Apply formatters and safe lint fixes
	ruff check --fix $(PY_SOURCES)
	ruff format $(PY_SOURCES)
	$(WEB) run format

test: test-backend test-poc test-web ## Run every test suite

test-backend: ## Platform backend tests
	cd platform/backend && $(PYTHON) -m pytest -q

test-poc: ## POC contract tests
	cd poc && $(PYTHON) -m pytest -q tests

test-web: ## Frontend unit tests
	$(WEB) test

build: ## Production build of the frontend
	$(WEB) run build

check: lint test build ## Everything CI runs except Docker and the dependency audit

up: ## Build and start the local Docker stack (migrations run first)
	$(COMPOSE) up --build -d --wait

down: ## Stop the local stack, keeping data volumes
	$(COMPOSE) down

logs: ## Follow logs from the local stack
	$(COMPOSE) logs -f --tail=100

seed: ## Seed demo accounts and the eight bundled tasks (no model calls)
	$(COMPOSE) run --rm seed

logins: ## Print the generated demo logins
	$(COMPOSE) run --rm --no-deps seed --show-logins

verify: ## Read-only checks of a seeded local stack
	$(COMPOSE) run --rm --no-deps --entrypoint python seed /workspace/platform/scripts/verify_docker_quickstart.py

migrate: ## Apply database migrations with the one-shot migrate service
	$(COMPOSE) run --rm migrate

prod-config: ## Render the production Compose configuration (fails if a required secret is missing)
	$(COMPOSE) -f platform/compose.prod.yaml config
