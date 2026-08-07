.DEFAULT_GOAL := help

.PHONY: help install lock upgrade run lint format format-check typecheck test check build clean

help: ## Show available commands
	@uv run python -c "import re; from pathlib import Path; text = Path('Makefile').read_text(); print('\n'.join(f'{m[0]:<16} {m[1]}' for m in re.findall(r'^([a-zA-Z_-]+):.*?## (.*)$$', text, re.MULTILINE)))"

install: ## Install project and development dependencies
	uv sync --all-groups

lock: ## Refresh the lock file without upgrading packages
	uv lock

upgrade: ## Upgrade all locked dependencies
	uv lock --upgrade

run: ## Run the application
	uv run python-template

lint: ## Run Ruff lint checks
	uv run ruff check .

format: ## Format source files
	uv run ruff format .
	uv run ruff check --fix .

format-check: ## Check formatting without changing files
	uv run ruff format --check .

typecheck: ## Run strict static type checking
	uv run mypy

test: ## Run tests with coverage
	uv run pytest

check: lint format-check typecheck test ## Run all quality checks

build: ## Build source and wheel distributions
	uv build

clean: ## Remove generated Python and tool artifacts
	uv run python -c "from pathlib import Path; import shutil; root = Path('.'); targets = [root / name for name in ('.coverage', '.mypy_cache', '.pytest_cache', '.ruff_cache', 'build', 'dist')] + list(root.rglob('__pycache__')); [shutil.rmtree(path) if path.is_dir() else path.unlink() for path in targets if path.exists()]"
