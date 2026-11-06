.PHONY: sync lint format format-check typecheck test ci

sync:
	pip install -e ".[dev]"

lint:
	ruff check src tests

format:
	ruff format src tests

format-check:
	ruff format --check src tests

typecheck:
	mypy src

test:
	python -m pytest -q

ci: lint format-check typecheck test
