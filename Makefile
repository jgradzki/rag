# One-command workflows for the RAG demo. Run `make` to list the targets.

.DEFAULT_GOAL := help

ifeq ($(OS),Windows_NT)
  # Recipes use POSIX sh syntax. On Windows run them with Git's sh and put Git's Unix
  # tools (cp, rm, awk) on PATH, so make works from PowerShell and cmd too, not only
  # from Git Bash. PROGRA~1 is the space-free short name of "Program Files".
  GIT_USR_BIN ?= C:/PROGRA~1/Git/usr/bin
  ifeq ($(wildcard $(GIT_USR_BIN)/sh.exe),)
    $(error Git's sh.exe not found in $(GIT_USR_BIN) - install Git for Windows or run: make GIT_USR_BIN=<your Git>/usr/bin ...)
  endif
  SHELL := $(GIT_USR_BIN)/sh.exe
  export PATH := $(GIT_USR_BIN);$(PATH)
  VENV_BIN := .venv/Scripts
  RAG_PYTHON ?= py -V:3.13
else
  VENV_BIN := .venv/bin
  RAG_PYTHON ?= python3.13
endif
# (RAG_PYTHON, not PYTHON: node-gyp and other tools set PYTHON in the environment.)

# --universal: one lock for every OS, with markers for platform-only packages (uvloop
# on Linux and macOS, colorama on Windows), so a lock made on Windows fits the Docker image.
UV_LOCK_FLAGS := -q --universal --python-version 3.13 --custom-compile-command "make lock"
# CI has no venv and passes UV=uv.
UV ?= $(VENV_BIN)/uv
# --python: without it uv syncs whatever venv is active in the shell, not backend/.venv.
UV_SYNC := pip sync -q --python .venv requirements-dev.txt
# lock-upgrade: every package, or only P=<package>.
UV_UPGRADE = $(if $(P),--upgrade-package $(P),--upgrade)
LOCK_STALE = { echo "backend/requirements*.txt are out of date - run: make lock"; exit 1; }

.PHONY: help setup lock lock-upgrade lock-check shots dev dev-backend dev-frontend test lint format check up down logs clean

help: ## Show this list
	@echo "Usage: make <target>"
	@awk 'BEGIN {FS = ":.*## "} /^[a-z-]+:.*## / {printf "  %-14s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

# --- Local development ---------------------------------------------------------

setup: ## Install all dependencies, create backend/.env, install git hooks
	cd backend && { [ -d .venv ] || $(RAG_PYTHON) -m venv .venv; }
	cd backend && $(VENV_BIN)/python -m pip install -q -r requirements-dev.txt
# Also removes packages that are no longer in the lock (installed by hand, or dropped).
	cd backend && $(VENV_BIN)/uv $(UV_SYNC)
	cd backend && { [ -f .env ] || cp .env.example .env; }
	cd frontend && npm ci
	backend/$(VENV_BIN)/pre-commit install
	@echo "Done. Set LLM_PROVIDER (and ANTHROPIC_API_KEY) in backend/.env, then run: make dev"

# uv keeps the versions already in the output files: `lock` changes only what the .in
# files require, `lock-upgrade` moves the pins (transitive ones too) to new releases.
lock: ## Re-pin every Python dependency after editing backend/requirements*.in
	cd backend && $(UV) pip compile $(UV_LOCK_FLAGS) -o requirements.txt requirements.in
	cd backend && $(UV) pip compile $(UV_LOCK_FLAGS) -o requirements-dev.txt requirements-dev.in
	cd backend && $(UV) $(UV_SYNC)

lock-upgrade: ## Upgrade the pins to the newest allowed releases (P=<package> for one)
	cd backend && $(UV) pip compile $(UV_LOCK_FLAGS) $(UV_UPGRADE) -o requirements.txt requirements.in
	cd backend && $(UV) pip compile $(UV_LOCK_FLAGS) $(UV_UPGRADE) -o requirements-dev.txt requirements-dev.in
	cd backend && $(UV) $(UV_SYNC)

# Re-locks into copies of the committed files, so it fails only when the .in files
# changed without `make lock` - not when a new release appears on PyPI. A uv error
# (no network) fails with uv's own message, not the "run make lock" hint.
lock-check: ## Fail if backend/requirements*.txt are out of date with the .in files
	cd backend && tmp=$$(mktemp -d) && trap 'rm -rf "$$tmp"' EXIT \
		&& cp requirements.txt requirements-dev.txt "$$tmp" \
		&& $(UV) pip compile $(UV_LOCK_FLAGS) -o "$$tmp/requirements.txt" requirements.in \
		&& { diff -u requirements.txt "$$tmp/requirements.txt" || $(LOCK_STALE); } \
		&& $(UV) pip compile $(UV_LOCK_FLAGS) -o "$$tmp/requirements-dev.txt" requirements-dev.in \
		&& { diff -u requirements-dev.txt "$$tmp/requirements-dev.txt" || $(LOCK_STALE); }

dev: ## Run backend (:8000) and frontend (:5173) with auto-reload; Ctrl+C stops both
	"$(MAKE)" -j2 --no-print-directory dev-backend dev-frontend

dev-backend: ## Run only the backend (http://localhost:8000/docs)
	cd backend && $(VENV_BIN)/uvicorn app.main:create_app --factory --reload --reload-dir app

dev-frontend: ## Run only the frontend (http://localhost:5173)
	cd frontend && npm run dev

shots: ## Retake the README screenshots (docs/screenshots) with the LLM set in backend/.env
	cd frontend && npm exec --no -- playwright install --only-shell chromium && npm run shots

# --- Quality -------------------------------------------------------------------

test: ## Run the backend tests
	cd backend && $(VENV_BIN)/python -m pytest -q

lint: ## Lint backend (ruff) and frontend (oxlint)
	cd backend && $(VENV_BIN)/ruff check . ../.claude
	cd frontend && npm run lint

format: ## Format backend (ruff) and frontend (prettier)
	cd backend && $(VENV_BIN)/ruff format . ../.claude
	cd frontend && npm run format

check: ## CI's checks: lock, lint, format check, tests, frontend build (CI also builds Docker images)
	"$(MAKE)" --no-print-directory lock-check
	cd backend && $(VENV_BIN)/ruff check . ../.claude
	cd backend && $(VENV_BIN)/ruff format --check . ../.claude
	cd backend && $(VENV_BIN)/python -m pytest -q
	cd frontend && npm run lint && npm run format:check && npm run build

# --- Docker --------------------------------------------------------------------

up: ## Build and start the app in Docker (http://localhost:8080)
	docker compose up --build -d
	@echo "App: http://localhost:8080 - the first start downloads the embedding model (make logs)"

down: ## Stop the Docker app (the index stays in the rag-data volume)
	docker compose down

logs: ## Follow the logs of the Docker app
	docker compose logs -f

clean: ## Remove build output and caches (keeps venv, node_modules and the index)
	rm -rf frontend/dist backend/.pytest_cache backend/.ruff_cache
