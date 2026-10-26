.DEFAULT_GOAL := help
PYTHON ?= python
VENV ?= .venv

.PHONY: help install lint fmt typecheck test cov web-test docs build run demo eval check clean

help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

install: ## Create a virtual environment and install the project with dev tools
	$(PYTHON) -m venv $(VENV)
	$(PYTHON) -m pip install --upgrade pip
	$(PYTHON) -m pip install -e ".[dev]"

lint: ## Run the linter
	$(PYTHON) -m ruff check .

fmt: ## Format the code
	$(PYTHON) -m ruff format .

typecheck: ## Run the static type checker
	$(PYTHON) -m mypy

test: ## Run the test suite
	$(PYTHON) -m pytest

cov: ## Run tests with a coverage report
	$(PYTHON) -m pytest --cov --cov-report=term-missing --cov-report=xml

web-test: ## Run the front-end module tests
	node --test src/draftproof/web/test

docs: ## Build the documentation site
	$(PYTHON) -m mkdocs build --strict

build: ## Build the wheel and sdist
	$(PYTHON) -m build

run: ## Start the API and studio UI
	$(PYTHON) -m draftproof serve

demo: ## Run the offline demo end to end
	$(PYTHON) -m draftproof demo

eval: ## Score the golden-case evaluation suite
	$(PYTHON) -m draftproof eval

check: lint typecheck test web-test ## Run every quality gate

clean: ## Remove build and cache artifacts
	rm -rf dist build site htmlcov .pytest_cache .mypy_cache .ruff_cache .coverage
