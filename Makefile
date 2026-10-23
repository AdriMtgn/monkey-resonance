SHELL := /bin/bash

COMPOSE ?= docker compose
COMPOSE_DEV ?= docker compose -f docker-compose.yml -f docker-compose.dev.yml

.PHONY: help build build-dev shell shell-dev run run-mcp run-api test lint logs up down restart exec dev-deps clean up-dev agent-serve agent-host agent-password agent

help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

build: ## Build the main (production) image
	$(COMPOSE) build

build-dev: ## Build the dev image (main image + pytest/ruff)
	$(COMPOSE_DEV) build

shell: ## Open a bash shell in the main image
	$(COMPOSE) run --rm mkr /bin/bash

shell-dev: ## Open a bash shell in the dev image
	$(COMPOSE_DEV) run --rm mkr /bin/bash

run: ## Run the app (interactive)
	$(COMPOSE) run --rm mkr python main.py

run-mcp: ## Run the app with the MCP server
	$(COMPOSE) run --rm mkr python main.py --with_mcp

run-api: ## Run the app with the API server
	$(COMPOSE) run --rm mkr python main.py --with_api

test: ## Run the test suite (needs dev image or `make dev-deps` first)
	$(COMPOSE_DEV) run --rm --workdir /base_app mkr python -m pytest tests/ app/ -v

lint: ## Lint with ruff (needs dev image or `make dev-deps` first)
	$(COMPOSE_DEV) run --rm --workdir /base_app mkr ruff check app/

logs: ## Follow the mkr service logs
	$(COMPOSE) logs -f mkr

up: ## Start the mkr service in the background
	$(COMPOSE) up -d mkr

down: ## Stop and remove the mkr service
	$(COMPOSE) down

restart: ## Restart the mkr service
	$(COMPOSE) restart mkr

exec: ## Exec an arbitrary command in the container (e.g. make exec CMD="ls -la")
	$(COMPOSE) exec mkr $(CMD)

dev-deps: ## Install dev deps (pytest, ruff) on-demand into the running container's venv
	$(COMPOSE) exec mkr uv pip install -r /base_app/requirements-dev.txt

clean: ## Stop, remove containers, local images and volumes
	$(COMPOSE) down --rmi local -v

# --- Agent OpenCode (dans le container dev) ----------------------------------

up-dev: ## Start the dev service (dev image + repo mounted + agent port)
	$(COMPOSE_DEV) up -d mkr

agent-serve: up-dev ## Start the OpenCode server in the dev container (port 4096)
	$(COMPOSE_DEV) exec mkr bash .devcontainer/scripts/agent-server.sh

agent-host: ## OpenCode TUI on the host, connected to the in-container server
	@test -f .devcontainer/tmp/opencode-password || { echo "Pas de mot de passe : lance 'make agent-serve' d'abord."; exit 1; }
	OPENCODE_PASSWORD="$$(cat .devcontainer/tmp/opencode-password)" opencode --server http://localhost:4096

agent-password: ## Print the agent server password (for OPENCODE_PASSWORD)
	@test -f .devcontainer/tmp/opencode-password || { echo "Pas de mot de passe : lance 'make agent-serve' d'abord."; exit 1; }
	@cat .devcontainer/tmp/opencode-password
	@echo

agent: ## OpenCode TUI inside the container (standalone, no server)
	$(COMPOSE_DEV) run --rm mkr opencode --standalone
